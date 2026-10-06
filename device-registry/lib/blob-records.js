import { del, get, list, put } from '@vercel/blob';
import { tokenHash, safeEqual } from './records.js';

const pathnameFor = (id) => `devices/${id}.json`;

export async function readRecord(id) {
  const result = await get(pathnameFor(id), { access: 'private' });
  if (!result || result.statusCode !== 200) return null;
  try {
    return JSON.parse(await new Response(result.stream).text());
  } catch {
    return null;
  }
}

export async function saveReport(report, knownExisting) {
  const pathname = pathnameFor(report.id);
  const existing = knownExisting === undefined ? await readRecord(report.id) : knownExisting;
  const hashedToken = tokenHash(report.token);
  if (existing && !safeEqual(existing.tokenHash, hashedToken)) return { ok: false, reason: 'unauthorized' };
  const now = new Date().toISOString();
  const record = {
    id: report.id,
    tokenHash: existing?.tokenHash || hashedToken,
    name: report.name,
    manufacturer: report.manufacturer,
    model: report.model,
    os: report.os,
    osVersion: report.osVersion,
    appVersion: report.appVersion,
    hardware: report.hardware,
    preflight: report.preflight,
    registeredAt: existing?.registeredAt || now,
    lastSeen: now,
  };
  await put(pathname, JSON.stringify(record), {
    access: 'private',
    addRandomSuffix: false,
    allowOverwrite: true,
    contentType: 'application/json',
    cacheControlMaxAge: 60,
  });
  return { ok: true, created: !existing };
}

export async function removeDevice(id, token) {
  const existing = await readRecord(id);
  if (!existing || !safeEqual(existing.tokenHash, tokenHash(token))) return false;
  await del(pathnameFor(id), { access: 'private' });
  return true;
}

export async function removeDeviceByAdmin(id) {
  await del(pathnameFor(id), { access: 'private' });
}

export async function listDevices() {
  const { blobs } = await list({ prefix: 'devices/', limit: 1000 });
  const devices = [];
  for (const blob of blobs) {
    const record = await readRecord(blob.pathname.replace(/^devices\//, '').replace(/\.json$/, ''));
    if (!record) continue;
    const { tokenHash: _tokenHash, ...safeRecord } = record;
    devices.push(safeRecord);
  }
  return devices.sort((a, b) => b.lastSeen.localeCompare(a.lastSeen));
}
