import { DEVICE_ID_RE, DEVICE_TOKEN_RE } from '../lib/records.js';
import { removeDevice } from '../lib/blob-records.js';

export const config = { api: { bodyParser: { sizeLimit: '8kb' } } };

export default async function handler(req, res) {
  res.setHeader('Cache-Control', 'no-store');
  if (req.method !== 'POST') return res.status(405).json({ error: 'Method not allowed' });
  const { id, token } = req.body || {};
  if (typeof id !== 'string' || !DEVICE_ID_RE.test(id) || typeof token !== 'string' || !DEVICE_TOKEN_RE.test(token)) {
    return res.status(400).json({ error: 'Invalid device credentials' });
  }
  try {
    const removed = await removeDevice(id, token);
    return removed ? res.status(200).json({ removed: true }) : res.status(404).json({ error: 'Device record not found' });
  } catch {
    return res.status(503).json({ error: 'Registry storage is temporarily unavailable' });
  }
}
