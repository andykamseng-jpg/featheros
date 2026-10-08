import { validateF2FRequest } from '../../lib/f2f.js';
import { authenticateF2FDevice, publishF2FMessage } from '../../lib/f2f-records.js';

export const config = { api: { bodyParser: { sizeLimit: '3mb' } } };

export default async function handler(req, res) {
  res.setHeader('Cache-Control', 'no-store');
  res.setHeader('X-Content-Type-Options', 'nosniff');
  if (req.method !== 'POST') return res.status(405).json({ error: 'Method not allowed' });
  const request = validateF2FRequest(req.body, 'publish');
  if (!request) return res.status(400).json({ error: 'Invalid FOSCP message' });
  try {
    if (!await authenticateF2FDevice(request.deviceId, request.deviceToken)) {
      return res.status(403).json({ error: 'Feather device token does not match' });
    }
    return res.status(200).json(await publishF2FMessage(request.deviceId, request.message));
  } catch {
    return res.status(503).json({ error: 'F2F relay storage is temporarily unavailable' });
  }
}
