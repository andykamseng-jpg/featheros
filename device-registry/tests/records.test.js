import test from 'node:test';
import assert from 'node:assert/strict';
import { safeEqual, tokenHash, validateReport } from '../lib/records.js';

const good = {
  id: 'a'.repeat(32), token: 'b'.repeat(64), name: 'ANDY-PC',
  manufacturer: 'Feather Test', model: 'Laptop', os: 'Windows',
  osVersion: '11', appVersion: '0.6.2', consent: true,
};

test('accepts only a bounded opted-in device report', () => {
  const cleaned = validateReport({ ...good, name: ' ANDY-PC\n', extra: 'ignored' });
  assert.equal(cleaned.name, 'ANDY-PC');
  assert.equal(cleaned.extra, undefined);
  assert.equal(cleaned.consent, undefined);
});

test('hardware is bounded and unique device paths and unknown fields are dropped', () => {
  const report = validateReport({ ...good, hardware: {
    firmwareMode: 'UEFI', bios: { version: '1.2', serial: 'private' },
    devices: [{ type: 'network_hardware', hardwareId: 'PCI\\VEN_8086&DEV_272B\\INSTANCE', name: 'Wi-Fi' }],
    drivers: Array.from({length: 300}, () => ({name: 'Wi-Fi', version: '1.0', secret: 'private'})),
  }});
  assert.equal(report.hardware.drivers.length, 200);
  assert.equal(report.hardware.devices[0].hardwareId, '');
  assert.equal(JSON.stringify(report).includes('private'), false);
});

test('rejects invalid credentials, missing consent, and missing fields', () => {
  assert.equal(validateReport({ ...good, id: 'bad' }), null);
  assert.equal(validateReport({ ...good, consent: false }), null);
  assert.equal(validateReport({ ...good, os: '' }), null);
});

test('device tokens are one-way hashed and comparisons require equal lengths', () => {
  assert.equal(tokenHash(good.token), tokenHash(good.token));
  assert.notEqual(tokenHash(good.token), good.token);
  assert.equal(safeEqual('abc', 'abc'), true);
  assert.equal(safeEqual('abc', 'ab'), false);
});
