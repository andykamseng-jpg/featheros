import test from 'node:test';
import assert from 'node:assert/strict';
import { FOSCP_MAX_BYTES, isHardwarePath, validateF2FRequest } from '../lib/f2f.js';

const deviceId = 'a'.repeat(32);
const deviceToken = 'b'.repeat(64);
const message = {
  protocol: 'FOSCP/1', id: 'c'.repeat(32), target: 'feather-source',
  integrity_sha256: 'd'.repeat(64), origin: { device_id: deviceId },
  compatibility: { scope: 'general' }, changes: [{ path: 'agent/example.py' }],
};

test('accepts a bounded code message for automatic publishing', () => {
  const request = validateF2FRequest({ device_id: deviceId, device_token: deviceToken, message }, 'publish');
  assert.equal(request.message.id, message.id);
  assert.equal(FOSCP_MAX_BYTES, 2 * 1024 * 1024);
});

test('rejects malformed identities, bad origin, unsafe paths, and oversized messages', () => {
  assert.equal(validateF2FRequest({ device_id: 'bad', device_token: deviceToken, message }, 'publish'), null);
  assert.equal(validateF2FRequest({ device_id: deviceId, device_token: deviceToken,
    message: { ...message, origin: { device_id: 'e'.repeat(32) } } }, 'publish'), null);
  assert.equal(validateF2FRequest({ device_id: deviceId, device_token: deviceToken,
    message: { ...message, changes: [{ path: '../secret.py' }] } }, 'publish'), null);
  assert.equal(validateF2FRequest({ device_id: deviceId, device_token: deviceToken,
    message: { ...message, description: 'x'.repeat(FOSCP_MAX_BYTES) } }, 'publish'), null);
});

test('machine-specific paths cannot be announced as general updates', () => {
  assert.equal(isHardwarePath('drivers/wifi.inf'), true);
  assert.equal(validateF2FRequest({ device_id: deviceId, device_token: deviceToken,
    message: { ...message, changes: [{ path: 'drivers/wifi.inf' }] } }, 'publish'), null);
  assert.ok(validateF2FRequest({ device_id: deviceId, device_token: deviceToken,
    message: { ...message, compatibility: { scope: 'machine', hardware_fingerprint: 'e'.repeat(64) },
      changes: [{ path: 'drivers/wifi.inf' }] } }, 'publish'));
});

test('pull cursors and batches are bounded', () => {
  assert.deepEqual(validateF2FRequest({ device_id: deviceId, device_token: deviceToken,
    cursor: '123|'.concat('a'.repeat(32)), limit: 2 }, 'pull'),
  { deviceId, deviceToken, cursor: '123|'.concat('a'.repeat(32)), limit: 2 });
  assert.equal(validateF2FRequest({ device_id: deviceId, device_token: deviceToken,
    cursor: 'invalid', limit: 2 }, 'pull'), null);
  assert.equal(validateF2FRequest({ device_id: deviceId, device_token: deviceToken,
    limit: 500 }, 'pull').limit, 2);
});
