import { validateF2FRequest } from '../../lib/f2f.js';
import { authenticateF2FDevice, pullF2FMessages } from '../../lib/f2f-records.js';

export const config = { api: { bodyParser: { sizeLimit: '8kb' } } };

export default async function handler(req, res) {
  res.setHeader('Cache-Control', 'no-store');
  res.setHeader('X-Content-Type-Options', 'nosniff');
  if (req.method !== 'POST') return res.status(405).json({ error: 'Method not allowed' });
  const request = validateF2FRequest(req.body, 'pull');
  if (!request) return res.status(400).json({ error: 'Invalid F2F pull request' });
  try {
    if (!await authenticateF2FDevice(request.deviceId, request.deviceToken)) {
      return res.status(403).json({ error: 'Feather device token does not match' });
    }
    return res.status(200).json(await pullF2FMessages(request.cursor, request.limit));
  } catch {
    return res.status(503).json({ error: 'F2F relay storage is temporarily unavailable' });
  }
}
