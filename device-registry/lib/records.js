import { createHash, timingSafeEqual } from 'node:crypto';

export const DEVICE_ID_RE = /^[a-f0-9]{32}$/i;
export const DEVICE_TOKEN_RE = /^[a-f0-9]{64}$/i;

export function tokenHash(token) {
  return createHash('sha256').update(token, 'utf8').digest('hex');
}

export function safeEqual(left, right) {
  const a = Buffer.from(String(left ?? ''), 'utf8');
  const b = Buffer.from(String(right ?? ''), 'utf8');
  return a.length === b.length && timingSafeEqual(a, b);
}

function clean(value, max = 120) {
  return typeof value === 'string' ? value.trim().replace(/[\u0000-\u001f\u007f]/g, '').slice(0, max) : '';
}

function hardwareReport(input) {
  const h = input && typeof input === 'object' && !Array.isArray(input) ? input : {};
  const obj = (v) => v && typeof v === 'object' && !Array.isArray(v) ? v : {};
  const b = obj(h.bios), board = obj(h.board);
  const list = (v, max) => Array.isArray(v) ? v.slice(0, max).map(obj) : [];
  const r = obj(h.resources);
  const integer = (v, max = Number.MAX_SAFE_INTEGER) => Number.isSafeInteger(v) && v >= 0 && v <= max ? v : null;
  return {
    resources: {
      processors: list(r.processors, 16).map(p => ({ name: clean(p.name, 100), cores: integer(p.cores, 4096), logicalProcessors: integer(p.logicalProcessors, 8192) })),
      memoryTotalBytes: integer(r.memoryTotalBytes), memoryAvailableBytes: integer(r.memoryAvailableBytes),
      graphics: list(r.graphics, 16).map(g => ({ name: clean(g.name, 100), reportedAdapterBytes: integer(g.reportedAdapterBytes) })),
      storage: list(r.storage, 16).map(d => ({ model: clean(d.model, 100), sizeBytes: integer(d.sizeBytes) })),
      modelFit: 'benchmark_required',
      graphicsMemoryNote: 'Reported adapter memory may be incomplete and is not a usable VRAM budget; integrated graphics shares system RAM.',
    },
    firmwareMode: ['BIOS', 'UEFI', 'unknown'].includes(h.firmwareMode) ? h.firmwareMode : 'unknown',
    secureBoot: typeof h.secureBoot === 'boolean' ? h.secureBoot : null,
    bios: { manufacturer: clean(b.manufacturer, 80), version: clean(b.version, 50) },
    board: { manufacturer: clean(board.manufacturer, 80), model: clean(board.model, 100) },
    devices: list(h.devices, 48).map(d => ({
      type: ['graphics', 'network_hardware'].includes(d.type) ? d.type : '',
      name: clean(d.name, 100),
      hardwareId: /^(PCI\\VEN_[0-9A-F]{4}&DEV_[0-9A-F]{4}|USB\\VID_[0-9A-F]{4}&PID_[0-9A-F]{4})$/i.test(d.hardwareId || '') ? d.hardwareId.toUpperCase() : '',
      driverVersion: clean(d.driverVersion, 40),
    })),
    drivers: list(h.drivers, 200).map(d => ({ name: clean(d.name, 100), version: clean(d.version, 40),
      provider: clean(d.provider, 80), signed: typeof d.signed === 'boolean' ? d.signed : null })),
  };
}

export function validateReport(body) {
  if (!body || typeof body !== 'object' || Array.isArray(body)) return null;
  const report = {
    id: clean(body.id, 32).toLowerCase(),
    token: clean(body.token, 64).toLowerCase(),
    name: clean(body.name, 80),
    manufacturer: clean(body.manufacturer, 80),
    model: clean(body.model, 100),
    os: clean(body.os, 40),
    osVersion: clean(body.osVersion, 50),
    appVersion: clean(body.appVersion, 32),
    preflight: ['scan_unavailable', 'replacement_image_not_available'].includes(body.preflight) ? body.preflight : 'replacement_image_not_available',
    hardware: hardwareReport(body.hardware),
    consent: body.consent === true,
  };
  if (!DEVICE_ID_RE.test(report.id) || !DEVICE_TOKEN_RE.test(report.token) || !report.consent) return null;
  if (!report.name || !report.os || !report.appVersion) return null;
  delete report.consent;
  return report;
}

export function adminAuthorized(req) {
  const expected = process.env.REGISTRY_ADMIN_KEY;
  const header = req.headers.authorization || '';
  return Boolean(expected && header.startsWith('Bearer ') && safeEqual(header.slice(7), expected));
}
