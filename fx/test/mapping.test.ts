import { test } from 'node:test';
import assert from 'node:assert/strict';
import { Learner, applyMapping, axisFromLearn, switchFromLearn, cleanMapping, DEFAULT_MAPPING, type Mapping } from '../src/mapping.ts';

const snap = (raw: Record<string, number>, channels: number[] | null = null, status = 'live') => ({
  status, controls: { roll: 0 }, raw: { roll: 0, pitch: 0, yaw: 0, throttle: -1024, arm: -1024, crash: -1024, ...raw }, channels,
});
const ch = (over: Record<number, number> = {}) => Array.from({ length: 16 }, (_, i) => over[i + 1] ?? 0);

test('default mapping reproduces the old behaviour (ch5 > 0 arms)', () => {
  const m = applyMapping(snap({ roll: 512, throttle: 1024, arm: 1024 }), DEFAULT_MAPPING);
  assert.deepEqual([m.live, m.roll, m.throttle, m.arm, m.flip], [true, 0.5, 1, true, null]);
  assert.equal(applyMapping(snap({ arm: -1024 }), DEFAULT_MAPPING).arm, false);
});

test('swapped inputs are fixed by remapping; reverse flips the sign', () => {
  const m: Mapping = { ...DEFAULT_MAPPING, roll: { src: 'in:yaw', rev: true }, yaw: { src: 'in:roll', rev: false } };
  const r = applyMapping(snap({ roll: 1024, yaw: 512 }), m);
  assert.equal(r.roll, -0.5);
  assert.equal(r.yaw, 1);
});

test('not live (stale, missing data) gives a resting, unknown frame', () => {
  assert.equal(applyMapping(snap({}, null, 'paused'), DEFAULT_MAPPING).live, false);
  const onCh: Mapping = { ...DEFAULT_MAPPING, roll: { src: 'ch:1', rev: false } };
  assert.equal(applyMapping(snap({}, null), onCh).live, false, 'channel source unavailable until the radio sends C records');
  assert.equal(applyMapping(snap({}, ch()), onCh).live, true);
});

test('learner picks the stick that moved, ignores a jittering one, and derives reverse', () => {
  const l = new Learner(['in:roll', 'in:pitch', 'in:yaw', 'in:throttle', 'ch:1', 'ch:2']);
  assert.equal(l.update(snap({}, ch()), 0), null);
  assert.equal(l.update(snap({ pitch: 40, yaw: -30 }, ch()), 100), null, 'small noise does not trigger');
  assert.equal(l.update(snap({ roll: -700 }, ch({ 1: -690 })), 200), null, 'waits for the movement to settle');
  const r = l.update(snap({ roll: -1000 }, ch({ 1: -990 })), 600)!;
  assert.equal(r.src, 'in:roll', 'stick input beats the mirrored mixer channel');
  assert.deepEqual(axisFromLearn(r), { src: 'in:roll', rev: true });
});

test('learner falls back to a channel when only the channel moves', () => {
  const l = new Learner(['in:roll', 'ch:2']);
  l.update(snap({}, ch()), 0);
  l.update(snap({}, ch({ 2: 800 })), 100);
  const r = l.update(snap({}, ch({ 2: 1000 })), 500)!;
  assert.equal(r.src, 'ch:2');
  assert.equal(axisFromLearn(r).rev, false);
});

test('switch learning stores a threshold between the two positions and the direction', () => {
  const l = new Learner(['ch:5', 'ch:8']);
  l.update(snap({}, ch({ 5: -1024, 8: 1024 })), 0);
  l.update(snap({}, ch({ 5: -1024, 8: -1024 })), 100);
  const r = l.update(snap({}, ch({ 5: -1024, 8: -1024 })), 500)!;
  assert.equal(r.src, 'ch:8');
  const sw = switchFromLearn(r);
  assert.deepEqual(sw, { src: 'ch:8', thr: 0, dir: -1 });
  const m: Mapping = { ...DEFAULT_MAPPING, arm: sw };
  assert.equal(applyMapping(snap({}, ch({ 8: -1024 })), m).arm, true);
  assert.equal(applyMapping(snap({}, ch({ 8: 1024 })), m).arm, false);
});

test('cleanMapping rejects junk and keeps the base', () => {
  const c = cleanMapping({ roll: { src: 'ch:99' }, pitch: { src: 'ch:3', rev: true }, arm: { src: 'ch:8', thr: 5, dir: 3 }, flip: { src: 'ch:6', thr: 10.4, dir: -1 } }, DEFAULT_MAPPING);
  assert.deepEqual(c.roll, DEFAULT_MAPPING.roll);
  assert.deepEqual(c.pitch, { src: 'ch:3', rev: true });
  assert.deepEqual(c.arm, DEFAULT_MAPPING.arm);
  assert.deepEqual(c.flip, { src: 'ch:6', thr: 10, dir: -1 });
  assert.equal(cleanMapping({ arm: null }, DEFAULT_MAPPING).arm, null);
});
