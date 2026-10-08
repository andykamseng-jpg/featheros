import { del, get, list, put } from '@vercel/blob';
import { tokenHash, safeEqual } from './records.js';

const devicePath = (id) => `f2f/devices/${id}.json`;
const messagePath = (id) => `f2f/messages/${id}.json`;
const RETENTION_MS = 30 * 24 * 60 * 60 * 1000;
const MAX_LIST = 1000;

async function readJson(pathname) {
  const result = await get(pathname, { access: 'private' });
  if (!result || result.statusCode !== 200) return null;
  try {
    return JSON.parse(await new Response(result.stream).text());
  } catch {
    return null;
  }
}

export async function authenticateF2FDevice(id, token) {
  const pathname = devicePath(id);
  const existing = await readJson(pathname);
  const hashedToken = tokenHash(token);
  if (existing && !safeEqual(existing.tokenHash, hashedToken)) return false;
  const now = new Date();
  if (!existing || now.getTime() - Date.parse(existing.lastSeen || 0) > 60 * 60 * 1000) {
    const record = { id, tokenHash: existing?.tokenHash || hashedToken,
      firstSeen: existing?.firstSeen || now.toISOString(), lastSeen: now.toISOString() };
    await put(pathname, JSON.stringify(record), { access: 'private', addRandomSuffix: false,
      allowOverwrite: true, contentType: 'application/json', cacheControlMaxAge: 60 });
  }
  return true;
}

async function pruneMessages(blobs, now = Date.now()) {
  const expired = blobs.filter(blob => {
    const uploadedAt = new Date(blob.uploadedAt).getTime();
    return Number.isFinite(uploadedAt) && now - uploadedAt > RETENTION_MS;
  }).slice(0, 100).map(blob => blob.pathname);
  if (expired.length) await del(expired, { access: 'private' });
}

export async function publishF2FMessage(deviceId, message) {
  const pathname = messagePath(message.id);
  let existing = await readJson(pathname);
  if (existing) return { accepted: true, duplicate: true, published_at: existing.publishedAt };

  const publishedAt = new Date().toISOString();
  const envelope = { id: message.id, senderId: deviceId, publishedAt, message };
  await put(pathname, JSON.stringify(envelope), { access: 'private', addRandomSuffix: false,
    allowOverwrite: false, contentType: 'application/json', cacheControlMaxAge: 60 });
  const { blobs } = await list({ prefix: 'f2f/messages/', limit: MAX_LIST });
  await pruneMessages(blobs);
  return { accepted: true, duplicate: false, published_at: publishedAt };
}

function cursorParts(cursor) {
  if (!cursor) return { time: 0, id: '' };
  const [rawTime, id] = cursor.split('|');
  return { time: Number(rawTime), id };
}

function blobCursor(blob) {
  const id = blob.pathname.replace(/^f2f\/messages\//, '').replace(/\.json$/, '');
  return { id, time: new Date(blob.uploadedAt).getTime(), value: id };
}

export async function pullF2FMessages(cursor = '', limit = 100) {
  const { blobs } = await list({ prefix: 'f2f/messages/', limit: MAX_LIST });
  await pruneMessages(blobs);
  const after = cursorParts(cursor);
  const ordered = blobs.map(blob => ({ blob, ...blobCursor(blob) }))
    .filter(row => /^[a-f0-9]{32}$/.test(row.id) && Number.isFinite(row.time) &&
      (row.time > after.time || (row.time === after.time && row.id > after.id)))
    .sort((a, b) => a.time - b.time || a.id.localeCompare(b.id));
  const batch = ordered.slice(0, limit);
  const updates = [];
  let nextCursor = cursor;
  for (const row of batch) {
    nextCursor = row.time + '|' + row.id;
    const envelope = await readJson(row.blob.pathname);
    if (envelope?.message && envelope.id === row.id) {
      updates.push({ cursor: nextCursor, sender_id: envelope.senderId,
        published_at: envelope.publishedAt, message: envelope.message });
    }
  }
  return { updates, cursor: nextCursor, more: ordered.length > batch.length };
}
