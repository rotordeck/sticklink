import { test } from 'node:test';
import assert from 'node:assert/strict';
import { DEFAULTS, clean, type FxConfig } from '../src/config.ts';
import { MAX_PARAM_LENGTH, decodeConfig, diff, encodeConfig, permalink } from '../src/permalink.ts';
import { PRESETS } from '../src/render/style.ts';

const STYLES = PRESETS.map((p) => p.id);
const copy = (c: FxConfig): FxConfig => JSON.parse(JSON.stringify(c));
/** Opening a link = decode, then validate like any untrusted input, on top of the defaults. */
const open = (param: string) => clean(decodeConfig(param)!, DEFAULTS, STYLES);

test('the defaults produce an empty difference; a link to the defaults still pins them', () => {
  assert.deepEqual(decodeConfig(encodeConfig(DEFAULTS, 'fx')), {});
  assert.deepEqual(open(encodeConfig(DEFAULTS, 'hud')), DEFAULTS);
  assert.ok(encodeConfig(DEFAULTS, 'fx').startsWith('v1.'));
});

test('a changed configuration round-trips exactly, and the link holds only what changed', () => {
  const cfg = copy(DEFAULTS);
  cfg.style = 'hacker'; cfg.chaos = 1.5; cfg.mode = 3; cfg.invert = ['pitch']; cfg.size = 720;
  cfg.mapping.roll = { src: 'ch:3', rev: true }; cfg.mapping.flip = { src: 'ch:9', thr: 0, dir: 1 };
  const param = encodeConfig(cfg, 'fx');
  assert.deepEqual(open(param), cfg);
  const raw = decodeConfig(param)!;
  assert.deepEqual(Object.keys(raw).sort(), ['chaos', 'invert', 'mapping', 'mode', 'size', 'style']);
  assert.deepEqual(raw.mapping, { roll: { src: 'ch:3', rev: true }, flip: { src: 'ch:9', thr: 0, dir: 1 } }, 'unchanged mapping entries are left out');
  assert.ok(param.length < 250, `short enough to share: ${param.length} characters`);
});

test('HUD links carry the HUD settings, not the stick-overlay ones, and round-trip nested changes', () => {
  const cfg = copy(DEFAULTS);
  cfg.chaos = 2; // an fx-only setting
  cfg.hud.layout = 'row'; cfg.hud.cells = 6; cfg.hud.style = 'synthwave'; cfg.hud.blocks.gps = false;
  cfg.hud.map = { provider: 'custom', customUrl: 'https://tiles.example.org/{z}/{x}/{y}.png', attribution: 'Tiles © Example — ünïcode ✓', zoom: 15, follow: false };
  const raw = decodeConfig(encodeConfig(cfg, 'hud'))!;
  assert.deepEqual(Object.keys(raw), ['hud'], 'no chaos, mode, size... in a HUD link');
  assert.deepEqual((raw.hud as any).blocks, { gps: false }, 'only the changed block switch');
  const reopened = open(encodeConfig(cfg, 'hud'));
  assert.deepEqual(reopened.hud, cfg.hud);
  assert.equal(reopened.chaos, DEFAULTS.chaos, 'fx settings fall back to the defaults');
  assert.equal((raw.hud as any).map.attribution, 'Tiles © Example — ünïcode ✓', 'unicode survives');
});

test('the permanent URL is origin + path + the parameter, and the address bar is never part of it', () => {
  const cfg = copy(DEFAULTS); cfg.style = 'inferno';
  const url = permalink('http://127.0.0.1:47613', '/hud/gps', cfg, 'hud');
  assert.ok(url.startsWith('http://127.0.0.1:47613/hud/gps?cfg=v1.'));
  assert.ok(!/[+/=\s]/.test(url.split('?cfg=')[1]), 'base64url: safe in a URL without escaping');
  assert.equal(new URL(url).searchParams.get('cfg'), encodeConfig(cfg, 'hud'));
});

test('a link reproduces the configuration whatever else is saved (it is applied on the defaults)', () => {
  const link = copy(DEFAULTS); link.style = 'hacker';
  const param = encodeConfig(link, 'fx');
  const saved = copy(DEFAULTS); saved.style = 'arcade'; saved.chaos = 0.2; saved.mode = 4; // what the server happens to hold
  void saved;
  assert.deepEqual(open(param), link, 'chaos and mode are the defaults, not the saved values');
});

test('bad links are rejected, never thrown on, and hostile content is cleaned like any input', () => {
  for (const bad of [null, undefined, '', 'v2.e30', 'e30', 'v1.', 'v1.!!!notbase64', 'v1.W10', 'v1.bnVsbA', 'v1.' + 'A'.repeat(MAX_PARAM_LENGTH)]) {
    assert.equal(decodeConfig(bad as any), null, String(bad).slice(0, 30));
  }
  const evil = 'v1.' + btoa(JSON.stringify({ style: '<script>', chaos: 'NaN', mode: 99, hud: { map: { provider: 'custom', customUrl: 'javascript:alert(1)//{z}{x}{y}' }, layout: 'x' }, mapping: { roll: { src: 'ch:99' } }, extra: 1 }))
    .replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
  const cfg = open(evil);
  assert.equal(cfg.hud.map.customUrl, '', 'the javascript: tile URL is dropped');
  const expected = copy(DEFAULTS); expected.hud.map.provider = 'custom'; // a valid value on its own; with no URL the map just shows the track
  assert.deepEqual(cfg, expected, 'every other invalid value falls back to the default');
});

test('diff: deep, ignores equal values, keeps nulls and arrays', () => {
  assert.equal(diff({ a: 1, b: { c: 2 } }, { a: 1, b: { c: 2 } }), undefined);
  assert.deepEqual(diff({ a: 1, b: { c: 3, d: 4 } }, { a: 1, b: { c: 2, d: 4 } }), { b: { c: 3 } });
  assert.deepEqual(diff({ s: null, l: ['a'] }, { s: 'x', l: [] }), { s: null, l: ['a'] });
  assert.deepEqual(diff({ z: 5 }, {}), { z: 5 });
});
