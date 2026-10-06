import { test } from 'node:test';
import assert from 'node:assert/strict';
import { CRIT, OK_GREEN, WARN, isWarm, makeLook } from '../src/hud/look.ts';
import { PRESETS } from '../src/render/style.ts';
import { badge } from '../src/hud/catalog.ts';

test('warm hues are recognised, cool ones and greys are not', () => {
  for (const warm of ['#ff5252', '#ffe14d', '#ff7a1a', '#ffd23f', '#ff3b3b', 'rgb(255,140,0)']) assert.ok(isWarm(warm), warm);
  for (const cool of ['#29e7ff', '#33ff66', '#00f0ff', '#ffffff', '#c9a7ff', '#7a00ff', '#888888', '#ff2bd6']) assert.ok(!isWarm(cool), cool);
});

test('a healthy value never looks like a warning, in any style', () => {
  for (const p of PRESETS) {
    const look = makeLook(p.style, 0);
    assert.notEqual(look.levelColor('ok'), WARN, p.id);
    assert.notEqual(look.levelColor('ok'), CRIT, p.id);
    assert.ok(look.style.rainbow || !isWarm(look.levelColor('ok')), `${p.id}: ok colour ${look.levelColor('ok')} must not be red/orange/yellow`);
    assert.equal(look.levelColor('warn'), WARN); assert.equal(look.levelColor('crit'), CRIT);
  }
  assert.equal(makeLook(PRESETS.find((p) => p.id === 'clean')!.style, 0).levelColor('ok'), OK_GREEN, 'clean has a red accent, so ok is green');
  assert.equal(makeLook(PRESETS.find((p) => p.id === 'neon')!.style, 0).levelColor('ok'), '#29e7ff', 'cool accents are kept');
});

test('a dBm value of 0 or more is "no signal", not a perfect reading', () => {
  const tel = { '1RSS': { value: -37, current: true, fresh: true, age_ms: 1 }, '2RSS': { value: 0, current: true, fresh: true, age_ms: 1 } };
  const units = { speed: 'kmh', alt: 'm' } as const;
  assert.equal(badge('1RSS', tel, units)!.level, 'ok');
  const b = badge('2RSS', tel, units)!;
  assert.deepEqual([b.text, b.level, b.frac, b.value], ['—', 'off', null, null]);
});
