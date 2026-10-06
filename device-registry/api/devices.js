import { adminAuthorized } from '../lib/records.js';
import { listDevices } from '../lib/blob-records.js';

export default async function handler(req, res) {
  res.setHeader('Cache-Control', 'no-store');
  res.setHeader('X-Content-Type-Options', 'nosniff');
  if (req.method !== 'GET') return res.status(405).json({ error: 'Method not allowed' });
  if (!adminAuthorized(req)) return res.status(401).json({ error: 'Dashboard key required' });
  try {
    return res.status(200).json({ devices: await listDevices() });
  } catch {
    return res.status(503).json({ error: 'Registry storage is temporarily unavailable' });
  }
}
