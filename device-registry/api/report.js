import { validateReport } from '../lib/records.js';
import { readRecord, saveReport } from '../lib/blob-records.js';

export const config = { api: { bodyParser: { sizeLimit: '8kb' } } };

const enrollmentCounts = new Map();
const HOUR_MS = 60 * 60 * 1000;

function allowEnrollment(req) {
  const forwarded = req.headers['x-forwarded-for'];
  const ip = (typeof forwarded === 'string' ? forwarded.split(',')[0] : 'unknown').trim().slice(0, 64);
  const now = Date.now();
  let record = enrollmentCounts.get(ip);
  if (!record || now - record.startedAt >= HOUR_MS) {
    record = { startedAt: now, count: 0 };
    enrollmentCounts.set(ip, record);
  }
  if (record.count >= 20) return false;
  record.count++;
  if (enrollmentCounts.size > 1000) {
    for (const [key, value] of enrollmentCounts) {
      if (now - value.startedAt >= HOUR_MS) enrollmentCounts.delete(key);
    }
  }
  return true;
}

export default async function handler(req, res) {
  res.setHeader('Cache-Control', 'no-store');
  res.setHeader('X-Content-Type-Options', 'nosniff');
  if (req.method !== 'POST') return res.status(405).json({ error: 'Method not allowed' });
  const report = validateReport(req.body);
  if (!report) return res.status(400).json({ error: 'Invalid or incomplete device report' });
  try {
    const existing = await readRecord(report.id);
    if (!existing && !allowEnrollment(req)) return res.status(429).json({ error: 'Too many new devices from this network; try later' });
    const result = await saveReport(report, existing);
    if (!result.ok) return res.status(401).json({ error: 'Device token did not match' });
    return res.status(result.created ? 201 : 200).json({ received: true });
  } catch {
    return res.status(503).json({ error: 'Registry storage is temporarily unavailable' });
  }
}
