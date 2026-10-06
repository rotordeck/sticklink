import { test } from 'node:test';
import assert from 'node:assert/strict';
import { LiveFeed, type LiveFrame } from '../src/live.ts';
import { clean, DEFAULTS } from '../src/config.ts';

const rest: LiveFrame = { live: true, roll: 0, pitch: 0, yaw: 0, throttle: 0.5, armed: true };
const run = (feed: LiveFeed, seconds: number, f: Partial<LiveFrame> | ((i: number) => Partial<LiveFrame>)) => {
  for (let i = 0; i < Math.round(seconds * feed.fps); i++) feed.push({ ...rest, ...(typeof f === 'function' ? f(i) : f) });
};
const kinds = (feed: LiveFeed) => feed.motion.events.map((e) => e.kind);

test('arm/disarm replace older events so the HUD fade follows the current state', () => {
  const feed = new LiveFeed(60, 2);
  run(feed, 0.5, { armed: false });
  run(feed, 0.5, { armed: true });
  run(feed, 0.5, { armed: false });
  run(feed, 0.5, { armed: true });
  assert.deepEqual(kinds(feed).filter((k) => k === 'arm' || k === 'disarm'), ['arm']);
  run(feed, 0.5, { armed: false });
  assert.deepEqual(kinds(feed).filter((k) => k === 'arm' || k === 'disarm'), ['arm', 'disarm']);
});

test('no arm event for the initial state or for unknown (null) arm status', () => {
  const feed = new LiveFeed(60, 2);
  run(feed, 0.5, { armed: null });
  run(feed, 0.5, { armed: true });
  assert.deepEqual(kinds(feed), []);
});

test('full-throttle span appears after 0.3 s, counts up, and closes with exact duration', () => {
  const feed = new LiveFeed(60, 2);
  run(feed, 0.5, { throttle: 0.5 });
  run(feed, 0.2, { throttle: 1 });
  assert.equal(kinds(feed).includes('full'), false, 'too short to show');
  run(feed, 0.4, { throttle: 1 });
  const e = feed.motion.events.find((x) => x.kind === 'full')!;
  assert.ok(e && e.end === Infinity);
  run(feed, 0.5, { throttle: 0.5 });
  assert.ok(Number.isFinite(e.end!));
  assert.ok(Math.abs(e.dur! - 0.6) < 0.05, `dur ${e.dur}`);
  const n = feed.frames - 1;
  assert.ok(Math.abs(feed.motion.stats.fullTotal[n] - e.dur!) < 1e-6);
});

test('hang time needs armed + recent flying; idling on the ground does not count', () => {
  const ground = new LiveFeed(60, 2);
  run(ground, 2, { throttle: 0 });
  assert.equal(kinds(ground).includes('hang'), false);
  const air = new LiveFeed(60, 2);
  run(air, 1, { throttle: 0.6 });
  run(air, 1, { throttle: 0 });
  assert.equal(kinds(air).includes('hang'), true);
  const disarmed = new LiveFeed(60, 2);
  run(disarmed, 1, { throttle: 0.6 });
  run(disarmed, 1, { throttle: 0, armed: false });
  assert.equal(kinds(disarmed).includes('hang'), false);
});

test('punch-out and a stick snap are detected once, then re-arm', () => {
  const feed = new LiveFeed(60, 2);
  run(feed, 0.6, { throttle: 0.1 });
  run(feed, 0.3, (i) => ({ throttle: Math.min(1, 0.1 + i / 12) }));
  assert.equal(kinds(feed).filter((k) => k === 'punch').length, 1);
  const snap = new LiveFeed(60, 2);
  run(snap, 0.5, {});
  run(snap, 0.3, { roll: 1 }); // roll is on the right stick in mode 2: 0 -> 1 in one frame
  assert.equal(kinds(snap).filter((k) => k === 'snap').length, 1);
  run(snap, 0.5, {});
  run(snap, 0.3, { roll: 1 });
  assert.equal(kinds(snap).filter((k) => k === 'snap').length, 2);
});

test('lost data (live=false) never triggers events and rests dots at centre', () => {
  const feed = new LiveFeed(60, 2);
  run(feed, 1, { live: false, throttle: 1, roll: 1 });
  assert.deepEqual(kinds(feed), []);
  assert.equal(feed.track.live[feed.frames - 1], 0);
});

test('compaction keeps memory bounded and event frames consistent', () => {
  const feed = new LiveFeed(60, 2, 300, 100);
  run(feed, 1, { throttle: 0.5 });
  run(feed, 1.5, { throttle: 1 }); // a full span still open across the compaction
  const open = feed.motion.events.find((e) => e.kind === 'full')!;
  const t0 = open.t0!;
  run(feed, 5, { throttle: 1 });
  assert.ok(feed.frames <= 300);
  assert.equal(open.end, Infinity);
  assert.ok(Math.abs(open.dur! - (feed.timeOf(feed.frames - 1) - t0)) < 0.02);
  assert.ok(open.frame < feed.frames, 'event frame stays in range after shifting');
  assert.ok(feed.track.start > 0);
});

test('config clean(): validates, clamps and keeps base for junk', () => {
  const styles = ['neon', 'arcade'];
  const c = clean({ style: 'arcade', chaos: '9', mode: '3', delay: '-5', invert: 'yaw,bogus,roll', size: 'x' }, DEFAULTS, styles);
  assert.deepEqual(c, { ...DEFAULTS, style: 'arcade', chaos: 2, mode: 3, delay: 0, invert: ['roll', 'yaw'] });
  assert.equal(clean({ style: '<script>' }, DEFAULTS, styles).style, DEFAULTS.style);
});

test('stick modes 1-4 put the right axes on the right gimbal', () => {
  const at = (mode: 1 | 2 | 3 | 4) => {
    const feed = new LiveFeed(60, mode);
    feed.push({ live: true, roll: 0.1, pitch: 0.2, yaw: 0.3, throttle: 0.9, armed: null });
    const m = feed.motion, r = (v: number) => Math.round(v * 100) / 100;
    return [r(m.lx[0]), r(m.ly[0]), r(m.rx[0]), r(m.ry[0])];
  };
  assert.deepEqual(at(1), [0.3, -0.2, 0.1, -0.8]);
  assert.deepEqual(at(2), [0.3, -0.8, 0.1, -0.2]);
  assert.deepEqual(at(3), [0.1, -0.2, 0.3, -0.8]);
  assert.deepEqual(at(4), [0.1, -0.8, 0.3, -0.2]);
});

// ---- retro-smoothing: radio readings every 3 frames (~20 Hz at 60 fps) ----
const reading = (feed: LiveFeed, roll: number, t: number, throttle = 0.5) =>
  feed.push({ ...rest, roll, throttle }, t);
const hold = (feed: LiveFeed, n: number, roll: number, throttle = 0.5) => {
  for (let k = 0; k < n; k++) feed.push({ ...rest, roll, throttle });
};
/** Push a signal sampled every 3 frames (50 ms): a reading frame followed by two projected frames. */
const drive = (feed: LiveFeed, readings: number, f: (k: number) => number) => {
  for (let k = 0; k < readings; k++) { reading(feed, f(k), k * 50); hold(feed, 2, f(k)); }
};

test('the frame carrying a reading shows it exactly (no lag)', () => {
  const feed = new LiveFeed(60, 2);
  drive(feed, 6, (k) => k * 0.1);
  reading(feed, 0.9, 300);
  assert.equal(Math.fround(feed.track.roll[feed.frames - 1]), Math.fround(0.9));
});

test('frames between readings are a smooth curve through them: no frozen frames, steady speed', () => {
  const feed = new LiveFeed(60, 2);
  drive(feed, 14, (k) => -0.8 + k * 0.1); // a steady ramp, each reading 0.1 higher
  reading(feed, -0.8 + 14 * 0.1, 14 * 50); // lets the previous interval be rewritten
  const r = feed.track.roll, from = 12, to = feed.frames - 2;
  const steps = [];
  for (let f = from; f < to; f++) steps.push(r[f + 1] - r[f]);
  assert.ok(steps.every((d) => d > 0.01), `a frozen/held frame survived: ${steps.map((d) => d.toFixed(3))}`);
  const min = Math.min(...steps), max = Math.max(...steps);
  assert.ok(max / min < 1.15, `ramp should advance evenly, steps ${min.toFixed(4)}..${max.toFixed(4)}`);
});

test('no speed spikes at the readings (the cause of the heavy dots / spark bursts)', () => {
  const smooth = new LiveFeed(60, 2), raw = new LiveFeed(60, 2);
  const f = (k: number) => Math.sin(k * 0.35) * 0.8;
  drive(smooth, 30, f);
  for (let k = 0; k < 30; k++) { raw.push({ ...rest, roll: f(k) }); raw.push({ ...rest, roll: f(k) }); raw.push({ ...rest, roll: f(k) }); }
  const spread = (feed: LiveFeed) => { const s = Array.from(feed.motion.speedR).slice(30, feed.frames - 6); return Math.max(...s) / (s.reduce((a, b) => a + b, 0) / s.length); };
  assert.ok(spread(smooth) < 1.6, `smoothed peak/mean speed ${spread(smooth).toFixed(2)}`);
  assert.ok(spread(raw) > 2, `held frames show the spikes this fixes: ${spread(raw).toFixed(2)}`);
});

test('curve never leaves the range of the real readings (no overshoot at full deflection)', () => {
  const feed = new LiveFeed(60, 2);
  const seq = [0, 0.5, 1, 1, 1, 0.5, 0, -1, -1, 0];
  drive(feed, seq.length, (k) => seq[k]);
  reading(feed, 0, seq.length * 50);
  for (let f = 0; f < feed.frames; f++) assert.ok(feed.track.roll[f] <= 1 + 1e-6 && feed.track.roll[f] >= -1 - 1e-6, `frame ${f}: ${feed.track.roll[f]}`);
});

test('between readings the head keeps moving, but only briefly and never past the stick range', () => {
  const feed = new LiveFeed(60, 2);
  drive(feed, 6, (k) => 0.5 + k * 0.1); // rising, newest reading 1.0
  reading(feed, 1.0, 6 * 50);
  const at = feed.frames - 1;
  hold(feed, 8, 1.0); // data stalls: eight more frames with no new reading
  assert.ok(feed.track.roll[at + 1] > 1.0 - 1e-6 && feed.track.roll[at + 1] <= 1, 'clamped at the stick limit');
  const lowStall = new LiveFeed(60, 2);
  drive(lowStall, 4, (k) => k * 0.1);
  reading(lowStall, 0.4, 4 * 50);
  const i0 = lowStall.frames - 1; hold(lowStall, 12, 0.4);
  const tail = Array.from(lowStall.track.roll.slice(i0, lowStall.frames));
  // 0.1 per reading, projected at most 60 ms at 85 % gain: about 0.102 ahead, then it stops
  assert.ok(Math.max(...tail) - tail[0] < 0.11, 'projection stops after ~60 ms instead of running away');
  assert.ok(Math.max(...tail) - tail[0] > 0.05, 'but it does move in between readings');
  assert.equal(tail.at(-1), tail.at(-3), 'then holds');
});

test('a gap or restart breaks the curve: nothing is interpolated across it', () => {
  const feed = new LiveFeed(60, 2);
  drive(feed, 5, (k) => k * 0.2);
  feed.push({ live: false, roll: 0, pitch: 0, yaw: 0, throttle: 0, armed: null });
  for (let k = 0; k < 4; k++) feed.push({ live: false, roll: 0, pitch: 0, yaw: 0, throttle: 0, armed: null });
  const before = Array.from(feed.track.roll.slice(0, feed.frames));
  reading(feed, 0.9, 5000); hold(feed, 2, 0.9); reading(feed, 0.9, 5050);
  assert.deepEqual(Array.from(feed.track.roll.slice(0, before.length)), before, 'history before the gap untouched');
  feed.breakReadings();
  reading(feed, -0.3, 100); hold(feed, 2, -0.3); reading(feed, -0.3, 150);
  assert.ok(Math.abs(feed.track.roll[feed.frames - 2] - -0.3) < 1e-6, 'no curve towards the stale reading');
});
