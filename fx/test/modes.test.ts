import { test } from 'node:test';
import assert from 'node:assert/strict';
import { AUX_CHANNELS, TICKS, auxLabel, fracToUs, inRange, moveHandle, rangeForPosition, rawToUs, snap, usToFrac } from '../src/modes/scale.ts';
import { DEFAULT_MODES, activeScenes, moveModeTo, winner, addRange, buildCards, moveMode, removeRange, setRange, type SceneModes } from '../src/modes/model.ts';
import { Learner } from '../src/mapping.ts';

const cfg = (modes: SceneModes['modes'] = []): SceneModes => ({ ...DEFAULT_MODES, modes });
const SCENES = ['Intro', 'Drone', 'Room', 'Replay'];

test('scale: snapping, positions on the track and the microsecond conversion (same as the server)', () => {
  assert.deepEqual([snap(1512), snap(1513), snap(850), snap(2300), snap(1700)], [1500, 1525, 900, 2100, 1700]);
  assert.equal(usToFrac(900), 0); assert.equal(usToFrac(2100), 1); assert.equal(usToFrac(1500), 0.5);
  assert.equal(usToFrac(0), 0, 'out of range values stay on the track');
  assert.equal(fracToUs(0.5), 1500); assert.equal(fracToUs(-1), 900); assert.equal(fracToUs(9), 2100);
  for (const us of [900, 1000, 1275, 1500, 2100]) assert.equal(fracToUs(usToFrac(us)), us, `round trip ${us}`);
  assert.deepEqual([-1024, 0, 1024, 512, -512, 2048].map(rawToUs), [1000, 1500, 2000, 1750, 1250, 2500]);
  assert.deepEqual(TICKS, [...TICKS].sort((a, b) => a - b));
  assert.equal(auxLabel('ch:5'), 'AUX 1'); assert.equal(auxLabel('ch:16'), 'AUX 12'); assert.equal(auxLabel('ch:3'), 'CH 3');
  assert.equal(AUX_CHANNELS.length, 12); assert.equal(AUX_CHANNELS[0], 'ch:5');
});

test('handles: the grid is respected and a handle cannot cross the other', () => {
  const r = { channel: 'ch:6', min: 1300, max: 1700 };
  assert.deepEqual(moveHandle(r, 'min', 1100), { ...r, min: 1100 });
  assert.deepEqual(moveHandle(r, 'min', 1900), { ...r, min: 1700 }, 'stops at max');
  assert.deepEqual(moveHandle(r, 'max', 1000), { ...r, max: 1300 }, 'stops at min');
  assert.deepEqual(moveHandle(r, 'max', 2500), { ...r, max: 2100 });
  assert.deepEqual(moveHandle(r, 'min', 1111), { ...r, min: 1100 });
  assert.equal(inRange(1300, r), true); assert.equal(inRange(1700, r), true); assert.equal(inRange(1701, r), false);
  assert.equal(inRange(null, r), false); assert.equal(inRange(undefined, r), false);
});

test('a switch position becomes the matching third of the scale', () => {
  assert.deepEqual(rangeForPosition('ch:6', 1000), { channel: 'ch:6', min: 900, max: 1300 });
  assert.deepEqual(rangeForPosition('ch:6', 1500), { channel: 'ch:6', min: 1300, max: 1700 });
  assert.deepEqual(rangeForPosition('ch:6', 2000), { channel: 'ch:6', min: 1700, max: 2100 });
  assert.deepEqual([1249, 1250, 1750, 1751].map((u) => rangeForPosition('c', u).min), [900, 1300, 1300, 1700]);
});

test('learning a switch: the existing detector picks the moved AUX channel and its final position', () => {
  const ch = (over: Record<number, number> = {}) => Array.from({ length: 16 }, (_, i) => over[i + 1] ?? 0);
  const state = (channels: number[]) => ({ status: 'live', controls: {}, raw: {}, channels });
  const l = new Learner(AUX_CHANNELS);
  l.update(state(ch({ 6: -1024 })), 0);
  l.update(state(ch({ 6: 1024 })), 100);
  const res = l.update(state(ch({ 6: 1024 })), 600)!;
  assert.equal(res.src, 'ch:6');
  assert.deepEqual(rangeForPosition(res.src, rawToUs(res.level)), { channel: 'ch:6', min: 1700, max: 2100 });
});

test('cards: used modes first in priority order; unused scenes follow in OBS order unless hidden', () => {
  const c = cfg([{ scene: 'Room', ranges: [{ channel: 'ch:6', min: 1300, max: 1700 }] }, { scene: 'Drone', ranges: [{ channel: 'ch:6', min: 900, max: 1300 }] }]);
  const all = buildCards(c, SCENES, false);
  assert.deepEqual(all.map((x) => [x.scene, x.used, x.priority]), [['Room', true, 1], ['Drone', true, 2], ['Intro', false, null], ['Replay', false, null]]);
  assert.deepEqual(buildCards(c, SCENES, true).map((x) => x.scene), ['Room', 'Drone'], 'hide unused modes');
  assert.deepEqual(buildCards(cfg(), SCENES, false).map((x) => x.scene), SCENES, 'a first-time user sees every scene');
  const missing = buildCards(cfg([{ scene: 'Gone', ranges: [{ channel: 'ch:5', min: 900, max: 1000 }] }]), SCENES, true);
  assert.equal(missing[0].inObs, false, 'a configured scene that OBS no longer has is flagged');
  const offline = buildCards(c, null, false);
  assert.deepEqual(offline.map((x) => x.scene), ['Room', 'Drone']); assert.equal(offline[0].inObs, null, 'OBS unknown');
});

test('edits: add, change, remove, reorder; every edit returns a new object', () => {
  let c = cfg();
  const original = JSON.stringify(c);
  c = addRange(c, 'Drone');
  assert.deepEqual(c.modes, [{ scene: 'Drone', ranges: [{ channel: 'ch:5', min: 1700, max: 2100 }] }]);
  assert.equal(JSON.stringify(cfg()), original);
  c = addRange(c, 'Drone', { channel: 'ch:7', min: 900, max: 1000 });
  c = addRange(c, 'Room', { channel: 'ch:6', min: 1300, max: 1700 });
  assert.deepEqual(c.modes.map((m) => [m.scene, m.ranges.length]), [['Drone', 2], ['Room', 1]], 'a new scene goes last (lowest priority)');
  c = setRange(c, 'Drone', 1, { channel: 'ch:8', min: 1000, max: 1100 });
  assert.deepEqual(c.modes[0].ranges[1], { channel: 'ch:8', min: 1000, max: 1100 });
  c = moveMode(c, 'Room', -1);
  assert.deepEqual(c.modes.map((m) => m.scene), ['Room', 'Drone']);
  assert.deepEqual(moveMode(c, 'Room', -1).modes.map((m) => m.scene), ['Room', 'Drone'], 'cannot move past the top');
  assert.deepEqual(moveMode(c, 'Drone', 1).modes.map((m) => m.scene), ['Room', 'Drone'], 'cannot move past the bottom');
  c = removeRange(c, 'Room', 0);
  assert.deepEqual(c.modes.map((m) => m.scene), ['Drone'], 'removing the last range un-uses the scene');
  let full = cfg();
  for (let i = 0; i < 12; i++) full = addRange(full, 'X');
  assert.equal(full.modes[0].ranges.length, 8, 'at most eight ranges per mode, like the server');
});

test('active scenes follow the live values, in priority order', () => {
  const c = cfg([{ scene: 'Replay', ranges: [{ channel: 'ch:9', min: 1700, max: 2100 }] }, { scene: 'Drone', ranges: [{ channel: 'ch:6', min: 1700, max: 2100 }] }]);
  assert.deepEqual(activeScenes(c, { 'ch:6': 2000, 'ch:9': 2000 }), ['Replay', 'Drone']);
  assert.deepEqual(activeScenes(c, { 'ch:6': 2000, 'ch:9': 1000 }), ['Drone']);
  assert.deepEqual(activeScenes(c, { 'ch:6': null }), []);
});

test('sorting: a mode can be dropped at any position, and the upper active scene wins', () => {
  const r = (ch: string) => [{ channel: ch, min: 1700, max: 2100 }];
  const c = cfg([{ scene: 'A', ranges: r('ch:5') }, { scene: 'B', ranges: r('ch:6') }, { scene: 'C', ranges: r('ch:7') }]);
  const order = (x: SceneModes) => x.modes.map((m) => m.scene).join('');
  assert.equal(order(moveModeTo(c, 'C', 0)), 'CAB');
  assert.equal(order(moveModeTo(c, 'A', 2)), 'BCA');
  assert.equal(order(moveModeTo(c, 'B', 1)), 'ABC', 'dropping where it already is changes nothing');
  assert.equal(order(moveModeTo(c, 'A', 99)), 'BCA', 'positions are clamped');
  assert.equal(order(moveModeTo(c, 'A', -5)), 'ABC');
  assert.equal(order(moveModeTo(c, 'Nope', 0)), 'ABC');
  assert.equal(order(c), 'ABC', 'the original is not modified');
  const both = { 'ch:5': 2000, 'ch:7': 2000 };
  assert.deepEqual(activeScenes(c, both), ['A', 'C']); assert.equal(winner(activeScenes(c, both)), 'A', 'two conditions met: the upper scene');
  assert.equal(winner(activeScenes(moveModeTo(c, 'C', 0), both)), 'C', 'sort C to the top and it wins instead');
  assert.equal(winner([]), null);
});
