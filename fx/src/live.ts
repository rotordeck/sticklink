// LiveFeed: builds the Track/Motion structures stickcam's renderer reads, one 60 fps frame at a time,
// from a live stick stream. Event rules mirror stickcam's motion.ts (snap, punch, full throttle, hang time,
// arm/disarm). Gyro/accelerometer events (flip, roll, spin, crash) need data the radio does not have.
import type { Track } from './track.ts';
import type { Motion, MotionEvent } from './motion.ts';
import { hermite, tangent } from './curve.ts';

export type StickMode = 1 | 2 | 3 | 4;
/** Mode 1: L yaw/pitch, R roll/thr. Mode 2: L yaw/thr, R roll/pitch. Mode 3: L roll/pitch, R yaw/thr. Mode 4: L roll/thr, R yaw/pitch. */
export const throttleLeft = (mode: StickMode) => mode === 2 || mode === 4;
/** stickcam's renderer only knows 'throttle on the left' (2) or 'on the right' (1). */
export const rendererMode = (mode: StickMode): 1 | 2 => (throttleLeft(mode) ? 2 : 1);

export interface LiveFrame {
  live: boolean;
  roll: number; pitch: number; yaw: number; // -1..1
  throttle: number; // 0..1
  armed: boolean | null; // null = unknown
}

const FULL_THR = 0.98, FULL_MIN = 0.3, ZERO_THR = 0.02, HANG_MIN = 0.5;
const SPAN_JOIN = 0.06, HANG_FLYING = 0.2, HANG_CONTEXT = 1.5;
const SNAP_SPEED = 5;
const HEAD_MAX_MS = 60; // how far past the newest reading the dot is projected
const HEAD_GAIN = 0.85; // fraction of the recent velocity used (a little under 1 limits overshoot at reversals)

interface Cand { start: number; last: number; event?: MotionEvent }
/** A real radio reading: the frame it was attached to, its radio time (ms) and the four axes. */
interface Reading { frame: number; t: number; v: [number, number, number, number] }

export class LiveFeed {
  readonly track: Track;
  readonly motion: Motion;
  private n = 0;
  private snapArmed: [boolean, boolean] = [true, true];
  private punchArmed = true;
  private full: Cand | null = null;
  private hang: Cand | null = null;
  private lastFlying = -Infinity;
  private prevArmed: boolean | null = null;
  private armT: number | null = null; private armedFor = 0;
  private fullDone = 0; private hangBest = 0;
  private readings: Reading[] = [];

  readonly fps: number;
  readonly mode: StickMode;
  private cap: number;
  private keep: number;

  constructor(fps = 60, mode: StickMode = 2, cap = 4096, keep = 900) {
    this.fps = fps; this.mode = mode; this.cap = cap; this.keep = keep;
    const mk = () => new Float32Array(cap);
    this.track = { fps, frames: 0, start: 0, roll: mk(), pitch: mk(), yaw: mk(), throttle: mk(),
      gyro: [mk(), mk(), mk()], motor: mk(), live: new Uint8Array(cap) };
    this.motion = { lx: mk(), ly: mk(), rx: mk(), ry: mk(), speedL: mk(), speedR: mk(), events: [],
      stats: { fullTotal: mk(), hangBest: mk(), armedTime: mk() } };
  }

  get frames() { return this.n; }
  timeOf(i: number) { return this.track.start + i / this.fps; }

  /** Drop old history (the renderer only looks back a few seconds) so memory stays bounded. */
  private compact() {
    const shift = this.n - this.keep, tr = this.track, m = this.motion;
    for (const a of [tr.roll, tr.pitch, tr.yaw, tr.throttle, tr.motor, ...tr.gyro, tr.live,
      m.lx, m.ly, m.rx, m.ry, m.speedL, m.speedR, m.stats.fullTotal, m.stats.hangBest, m.stats.armedTime]) {
      a.copyWithin(0, shift, this.n);
    }
    tr.start += shift / this.fps;
    this.n = this.keep;
    this.readings = this.readings.map((r) => ({ ...r, frame: r.frame - shift })).filter((r) => r.frame >= 0);
    m.events = m.events.filter((e) => (e.end ?? e.frame) >= shift);
    for (const e of m.events) { e.frame -= shift; if (e.end !== undefined && e.end !== Infinity) e.end -= shift; }
  }

  /** Forget the reading history (radio restarted or data lost), so no curve is drawn across the gap. */
  breakReadings() { this.readings = []; }

  private setAxes(i: number, v: readonly number[]) {
    const tr = this.track;
    tr.roll[i] = v[0]; tr.pitch[i] = v[1]; tr.yaw[i] = v[2]; tr.throttle[i] = v[3]; tr.motor[i] = v[3];
    const m = this.motion;
    [m.lx[i], m.ly[i], m.rx[i], m.ry[i]] = this.positions(i);
  }

  /** Dot speed (full-scale units/s), one-pole smoothed (~35 ms) like stickcam, recomputed over a frame range. */
  private recomputeSpeed(from: number, to: number) {
    const tr = this.track, m = this.motion, a = 1 - Math.exp(-1 / (0.035 * this.fps));
    for (let j = Math.max(0, from); j <= to; j++) {
      for (const [x, y, s] of [[m.lx, m.ly, m.speedL], [m.rx, m.ry, m.speedR]] as const) {
        const raw = j > 0 && tr.live[j] && tr.live[j - 1] ? Math.hypot(x[j] - x[j - 1], y[j] - y[j - 1]) * this.fps : 0;
        const prev = j > 0 ? s[j - 1] : 0;
        s[j] = prev + a * (raw - prev);
      }
    }
  }

  /** A fresh reading arrived at frame i: redraw the frames since the previous reading as a smooth curve between the two. */
  private rewriteSince(i: number, cur: Reading): number {
    const R = this.readings, prev = R.at(-1);
    if (!prev || i - prev.frame < 2) return i;
    const pts = [...R.slice(-3), cur], xs = pts.map((p) => p.frame), k = pts.length - 2; // interval = pts[k] .. pts[k+1]
    const h = cur.frame - prev.frame;
    const m = [0, 1, 2, 3].map((axis) => {
      const ys = pts.map((p) => p.v[axis]);
      return [tangent(xs, ys, k), tangent(xs, ys, k + 1)] as const;
    });
    for (let fr = prev.frame + 1; fr < cur.frame; fr++) {
      const u = (fr - prev.frame) / h;
      this.setAxes(fr, [0, 1, 2, 3].map((axis) => hermite(prev.v[axis], m[axis][0], cur.v[axis], m[axis][1], h, u)));
    }
    return prev.frame + 1;
  }

  /** Where the dot is projected to, a little past the newest reading, so it keeps moving between readings. */
  private head(i: number, fallback: readonly number[]): number[] {
    const R = this.readings, last = R.at(-1), before = R.at(-2);
    if (!last || !before || last.t <= before.t) return [...fallback];
    const age = Math.min(HEAD_MAX_MS, ((i - last.frame) * 1000) / this.fps), dt = last.t - before.t;
    return [0, 1, 2, 3].map((a) => {
      const y = last.v[a] + ((last.v[a] - before.v[a]) / dt) * age * HEAD_GAIN;
      return a === 3 ? Math.max(0, Math.min(1, y)) : Math.max(-1, Math.min(1, y));
    });
  }

  /**
   * Append one display frame. `sampleT` (radio ms) marks a fresh reading: its values are used exactly (no lag) and the
   * frames since the previous reading are rewritten as a smooth curve. Other frames project from the last readings.
   */
  push(f: LiveFrame, sampleT?: number) {
    if (this.n >= this.cap) this.compact();
    const i = this.n++, tr = this.track, m = this.motion;
    tr.frames = this.n;
    tr.live[i] = f.live ? 1 : 0;
    let from = i;
    const exact: [number, number, number, number] = [f.roll, f.pitch, f.yaw, f.throttle];
    if (!f.live) { this.readings = []; this.setAxes(i, exact); }
    else if (sampleT !== undefined) {
      const cur: Reading = { frame: i, t: sampleT, v: exact };
      this.setAxes(i, exact);
      from = this.rewriteSince(i, cur);
      this.readings = [...this.readings.slice(-3), cur];
    } else this.setAxes(i, this.head(i, exact));
    this.recomputeSpeed(from, i);

    const t = this.timeOf(i);
    if (f.live) {
      this.detectSnaps(i);
      this.detectPunch(i);
    }
    this.armEvents(i, t, f);
    this.spans(i, t, f);
    this.stats(i, t);
  }

  /** Dot positions (gimbal units, y down: stick up = -1) for the chosen stick mode. */
  private positions(i: number): [number, number, number, number] {
    const tr = this.track, thrY = 1 - 2 * tr.throttle[i], pitchY = -tr.pitch[i], yaw = tr.yaw[i], roll = tr.roll[i];
    switch (this.mode) {
      case 1: return [yaw, pitchY, roll, thrY];
      case 3: return [roll, pitchY, yaw, thrY];
      case 4: return [roll, thrY, yaw, pitchY];
      default: return [yaw, thrY, roll, pitchY];
    }
  }

  private detectSnaps(i: number) {
    const m = this.motion, thrOnLeft = throttleLeft(this.mode);
    ([[m.lx, m.ly, m.speedL, 0], [m.rx, m.ry, m.speedR, 1]] as const).forEach(([x, y, s, side]) => {
      const useY = thrOnLeft ? side === 1 : side === 0;
      const r = useY ? Math.max(Math.abs(x[i]), Math.abs(y[i])) : Math.abs(x[i]);
      if (this.snapArmed[side] && r > 0.95 && s[i] > SNAP_SPEED) {
        m.events.push({ frame: i, kind: 'snap', side, x: x[i], y: y[i] });
        this.snapArmed[side] = false;
      } else if (r < 0.8) this.snapArmed[side] = true;
    });
  }

  private detectPunch(i: number) {
    const tr = this.track, m = this.motion, look = Math.max(1, Math.round(0.4 * this.fps));
    const th = tr.throttle[i];
    if (this.punchArmed && i >= look) {
      let lo = 1;
      for (let k = i - look; k < i; k++) if (tr.live[k] && tr.throttle[k] < lo) lo = tr.throttle[k];
      if (lo < 0.35 && th - lo > 0.45) {
        const side: 0 | 1 = throttleLeft(this.mode) ? 0 : 1;
        m.events.push({ frame: i, kind: 'punch', side, x: side ? m.rx[i] : m.lx[i], y: side ? m.ry[i] : m.ly[i], label: 'PUNCH IT' });
        this.punchArmed = false;
      }
    } else if (th < 0.3) this.punchArmed = true;
  }

  /** The renderer fades the HUD from the first arm/disarm event, so keep only the current ones. */
  private armEvents(i: number, t: number, f: LiveFrame) {
    const ev = this.motion.events;
    if (f.armed !== null) {
      if (this.prevArmed !== null && f.armed !== this.prevArmed) {
        const kind = f.armed ? 'arm' : 'disarm';
        for (let k = ev.length - 1; k >= 0; k--) if (ev[k].kind === 'disarm' || (f.armed && ev[k].kind === 'arm')) ev.splice(k, 1);
        ev.push({ frame: i, kind, label: f.armed ? 'ARMED' : 'DISARMED' });
        if (f.armed) { this.armT = t; this.armedFor = 0; }
      }
      if (this.prevArmed === null && f.armed) this.armT = t;
      this.prevArmed = f.armed;
    }
    if (this.armT !== null && this.prevArmed) this.armedFor = t - this.armT;
  }

  /** Full-throttle and hang-time spans, detected as they happen (event appears once long enough). */
  private spans(i: number, t: number, f: LiveFrame) {
    const thr = this.track.throttle[i], ev = this.motion.events;
    const armed = f.armed !== false;
    if (f.live && armed && thr > HANG_FLYING) this.lastFlying = t;
    const run = (c: Cand | null, inside: boolean, min: number, kind: 'full' | 'hang', label: string, ok: (c: Cand) => boolean): Cand | null => {
      if (inside) {
        if (!c) c = { start: t, last: t };
        c.last = t;
        if (!c.event && t - c.start >= min && ok(c)) {
          c.event = { frame: i, kind, label, t0: c.start, dur: t - c.start, end: Infinity };
          ev.push(c.event);
        }
        if (c.event) c.event.dur = t - c.start;
      } else if (c && t - c.last > SPAN_JOIN) {
        if (c.event) {
          c.event.end = i; c.event.dur = c.last - c.start;
          if (kind === 'full') this.fullDone += c.event.dur; else this.hangBest = Math.max(this.hangBest, c.event.dur);
        }
        return null;
      }
      return c;
    };
    this.full = run(this.full, f.live && thr >= FULL_THR, FULL_MIN, 'full', 'FULL SEND', () => true);
    this.hang = run(this.hang, f.live && armed && thr <= ZERO_THR, HANG_MIN, 'hang', 'HANG TIME',
      (c) => c.start - this.lastFlying <= HANG_CONTEXT);
  }

  private stats(i: number, t: number) {
    const st = this.motion.stats;
    st.fullTotal[i] = this.fullDone + (this.full?.event ? this.full.event.dur! : 0);
    st.hangBest[i] = Math.max(this.hangBest, this.hang?.event ? this.hang.event.dur! : 0);
    st.armedTime[i] = this.armedFor;
  }
}
