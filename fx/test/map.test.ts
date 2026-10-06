import { test } from 'node:test';
import assert from 'node:assert/strict';
import { TileMap } from '../src/hud/map.ts';

// A fake image whose load is controlled by the test, so policy behaviour can be checked without a network.
const loads: { url: string; ok: () => void; fail: () => void }[] = [];
const fakeImage = () => {
  const img: any = { decoding: '', onload: null, onerror: null, _src: '' };
  Object.defineProperty(img, 'src', { get: () => img._src, set(v: string) { img._src = v; if (v) loads.push({ url: v, ok: () => img.onload?.(), fail: () => img.onerror?.() }); } });
  return img as HTMLImageElement;
};
const fresh = () => { loads.length = 0; return new TileMap(fakeImage); };

test('at most four tiles load at once; the rest wait, and nothing outside what is asked for is fetched', () => {
  const tm = fresh();
  tm.beginFrame();
  for (let i = 0; i < 9; i++) tm.get(`https://t.example/${i}.png`, 0);
  assert.equal(loads.length, 4, 'only four requests in flight');
  loads[0].ok(); loads[1].ok();
  assert.equal(loads.length, 6, 'a finished load frees a slot for the next queued tile');
  assert.deepEqual(loads.map((l) => l.url).slice(4), ['https://t.example/4.png', 'https://t.example/5.png']);
});

test('a tile is requested once however often it is asked for; a new frame forgets the queue (no prefetch backlog)', () => {
  const tm = fresh();
  for (let f = 0; f < 5; f++) { tm.beginFrame(); tm.get('https://t.example/a.png', f); }
  assert.equal(loads.length, 1);
  const q = fresh();
  q.beginFrame();
  for (let i = 0; i < 6; i++) q.get(`https://t.example/${i}.png`, 0);
  q.beginFrame(); // the view moved on: tiles 4 and 5 are no longer wanted
  loads[0].ok(); loads[1].ok(); loads[2].ok(); loads[3].ok();
  assert.equal(loads.length, 4, 'queued tiles that are no longer visible are never fetched');
});

test('results: ok, error, and a failed tile is not retried every frame', () => {
  const tm = fresh();
  tm.beginFrame();
  const e = tm.get('https://t.example/x.png', 0)!;
  assert.equal(e.state, 'loading');
  loads[0].ok();
  assert.equal(tm.get('https://t.example/x.png', 1)!.state, 'ok');
  const bad = tm.get('https://t.example/y.png', 1)!;
  loads[1].fail();
  assert.equal(tm.get('https://t.example/y.png', 5)!.state, 'error');
  assert.equal(loads.length, 2, 'no retry yet');
  void bad;
});

test('the cache is bounded', () => {
  const tm = fresh();
  for (let i = 0; i < 300; i++) { tm.beginFrame(); tm.get(`https://t.example/${i}.png`, i); if (loads.length) loads.at(-1)!.ok(); }
  assert.ok((tm as any).cache.size <= 81, `cache size ${(tm as any).cache.size}`);
});
