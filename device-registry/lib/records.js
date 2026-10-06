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
