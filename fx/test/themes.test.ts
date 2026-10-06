import test from 'node:test';
import assert from 'node:assert/strict';
import { PRESETS, STYLE_IDS, presetById, registerThemes } from '../src/render/style.ts';

const core = PRESETS.length;

test('a theme is a built-in preset with some settings changed', () => {
  registerThemes([{ id: 'gold', name: 'Gold', description: 'warm', base: 'neon', style: { ring: '#ffc933', glow: 0.9 } }]);
  assert.equal(PRESETS.length, core + 1);
  const gold = presetById('gold');
  assert.equal(gold.name, 'Gold');
  assert.equal(gold.blurb, 'warm');
  assert.equal(gold.style.ring, '#ffc933');
  assert.equal(gold.style.glow, 0.9);
  assert.equal(gold.style.trail, presetById('neon').style.trail, 'untouched settings come from the base');
  assert.ok(STYLE_IDS.includes('gold'));
  assert.equal(presetById('neon').style.ring, '#29e7ff', 'the base preset itself is not modified');
});

test('registering again replaces the earlier themes; built-in ids cannot be taken; broken themes are skipped', () => {
  registerThemes([{ id: 'one', name: 'One' }, { id: 'neon', name: 'Fake neon', style: { ring: 'red' } }, { id: 'bad', name: 'Bad', error: 'oops' }]);
  assert.deepEqual(STYLE_IDS.slice(core), ['one']);
  assert.equal(presetById('neon').name, 'Neon');
  registerThemes([{ id: 'two', name: 'Two', base: 'does-not-exist' }]);
  assert.deepEqual(STYLE_IDS.slice(core), ['two']);
  assert.equal(presetById('two').style.frame, presetById('clean').style.frame, 'an unknown base falls back to clean');
  registerThemes([]);
  assert.equal(PRESETS.length, core);
  assert.equal(presetById('two').id, PRESETS[0].id, 'a removed theme falls back to the first preset');
});

test('theme label maps are copies, not shared with the base', () => {
  registerThemes([{ id: 'labels', name: 'L', base: 'hacker', style: { labelMap: { WASTED: 'BOOM' } } }]);
  assert.equal(presetById('labels').style.labelMap.WASTED, 'BOOM');
  assert.notEqual(presetById('hacker').style.labelMap.WASTED, 'BOOM');
  registerThemes([]);
});
