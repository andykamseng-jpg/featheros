import { DEVICE_ID_RE, adminAuthorized } from '../lib/records.js';
import { removeDeviceByAdmin } from '../lib/blob-records.js';

export const config = { api: { bodyParser: { sizeLimit: '8kb' } } };

export default async function handler(req, res) {
  res.setHeader('Cache-Control', 'no-store');
  if (req.method !== 'POST') return res.status(405).json({ error: 'Method not allowed' });
  if (!adminAuthorized(req)) return res.status(401).json({ error: 'Dashboard key required' });
  const { id } = req.body || {};
  if (typeof id !== 'string' || !DEVICE_ID_RE.test(id)) return res.status(400).json({ error: 'Invalid device ID' });
  try {
    await removeDeviceByAdmin(id);
    return res.status(200).json({ removed: true });
  } catch {
    return res.status(503).json({ error: 'Registry storage is temporarily unavailable' });
  }
}
