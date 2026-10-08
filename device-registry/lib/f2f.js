import { DEVICE_ID_RE, DEVICE_TOKEN_RE } from './records.js';

export const FOSCP_MAX_BYTES = 2 * 1024 * 1024;
export const F2F_CURSOR_RE = /^(\d{1,13})\|([a-f0-9]{32})$/;
const BLOCKED_PARTS = new Set(['.git', '.env', '__pycache__', 'node_modules', 'feather-data']);
const HARDWARE_PARTS = new Set(['driver', 'drivers', 'device', 'devices', 'hardware', 'firmware',
  'boot', 'kernel', 'gpu', 'graphics']);
const HARDWARE_SUFFIXES = new Set(['.inf', '.sys', '.ko', '.rom']);

function validFoscpPath(value) {
  if (typeof value !== 'string' || !value || value.length > 300 || value.includes('\\') || value.includes('\0')) return false;
  const parts = value.split('/');
  if (value.startsWith('/') || parts.some(part => !part || part === '.' || part === '..')) return false;
  return !parts.some(part => BLOCKED_PARTS.has(part.toLowerCase()));
}

export function isHardwarePath(path) {
  const parts = path.toLowerCase().split('/');
  const suffix = path.toLowerCase().slice(path.lastIndexOf('.'));
  return parts.some(part => HARDWARE_PARTS.has(part)) || HARDWARE_SUFFIXES.has(suffix);
}

export function validateF2FRequest(body, action) {
  if (!body || typeof body !== 'object' || Array.isArray(body)) return null;
  const deviceId = typeof body.device_id === 'string' ? body.device_id.toLowerCase() : '';
  const deviceToken = typeof body.device_token === 'string' ? body.device_token.toLowerCase() : '';
  if (!DEVICE_ID_RE.test(deviceId) || !DEVICE_TOKEN_RE.test(deviceToken)) return null;

  if (action === 'publish') {
    const message = body.message;
    if (!message || typeof message !== 'object' || Array.isArray(message) ||
        Buffer.byteLength(JSON.stringify(message), 'utf8') > FOSCP_MAX_BYTES ||
        message.protocol !== 'FOSCP/1' || message.target !== 'feather-source' ||
        typeof message.id !== 'string' || !/^[a-f0-9]{32}$/.test(message.id) ||
        typeof message.integrity_sha256 !== 'string' || !/^[a-f0-9]{64}$/.test(message.integrity_sha256) ||
        message.origin?.device_id !== deviceId || !Array.isArray(message.changes) ||
        message.changes.length < 1 || message.changes.length > 32 ||
        !['general', 'machine'].includes(message.compatibility?.scope)) return null;
    if (message.compatibility.scope === 'machine' &&
        !/^[a-f0-9]{64}$/.test(message.compatibility.hardware_fingerprint || '')) return null;
    let hasHardware = false;
    const seen = new Set();
    for (const change of message.changes) {
      if (!change || typeof change !== 'object' || !validFoscpPath(change.path) || seen.has(change.path)) return null;
      seen.add(change.path);
      hasHardware ||= isHardwarePath(change.path);
    }
    if (hasHardware && message.compatibility.scope !== 'machine') return null;
    return { deviceId, deviceToken, message };
  }

  if (action === 'pull') {
    const cursor = typeof body.cursor === 'string' ? body.cursor : '';
    if (cursor && !F2F_CURSOR_RE.test(cursor)) return null;
    const limit = Number.isSafeInteger(body.limit) ? Math.min(2, Math.max(1, body.limit)) : 2;
    return { deviceId, deviceToken, cursor, limit };
  }
  return null;
}
