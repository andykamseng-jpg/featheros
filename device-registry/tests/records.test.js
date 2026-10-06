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
