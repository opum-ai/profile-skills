import { test } from 'node:test';
import assert from 'node:assert/strict';
import { installOrder, resolve } from '../src/graph.ts';

const ws = { packages: [
  { name: 'app', version: '1.0.0', deps: ['lib', 'utils'] },
  { name: 'lib', version: '2.1.0', deps: ['utils'] },
  { name: 'utils', version: '0.3.1', deps: [] },
  { name: 'cli', version: '1.0.0', deps: ['app'] },
  { name: 'aaa', version: '1.0.0', deps: [] },
] };

test('dependencies come first; ties broken alphabetically', () => {
  assert.deepEqual(installOrder(ws), ['aaa', 'utils', 'lib', 'app', 'cli']);
});

test('cycle is reported with members', () => {
  assert.throws(() => installOrder({ packages: [{ name: 'a', version: '1', deps: ['b'] }, { name: 'b', version: '1', deps: ['a'] }] }), /cycle among: a, b/);
});

test('unknown dependency is rejected', async () => {
  await assert.rejects(resolve({ packages: [{ name: 'a', version: '1', deps: ['zzz'] }] }), /unknown package zzz/);
});

test('levels and manifests follow the order', async () => {
  const r = await resolve(ws);
  assert.deepEqual(r.manifests.map((m) => m.name), r.order);
  assert.equal(r.levels.cli, 3);
  assert.equal(r.levels.aaa, 0);
});
