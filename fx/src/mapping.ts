// Which radio value drives which function, and the "learn by moving it" detector. Pure logic, no DOM.

export type Src = string; // 'in:roll' | 'in:pitch' | 'in:yaw' | 'in:throttle' | 'in:arm' | 'in:crash' | 'ch:1'..'ch:16'
export interface AxisMap { src: Src; rev: boolean }
/** Active when the raw value is above (dir 1) or below (dir -1) `thr`. */
export interface SwitchMap { src: Src; thr: number; dir: 1 | -1 }
export interface Mapping {
  roll: AxisMap; pitch: AxisMap; yaw: AxisMap; throttle: AxisMap;
  arm: SwitchMap | null; flip: SwitchMap | null;
}
export type AxisName = 'roll' | 'pitch' | 'yaw' | 'throttle';
export const AXIS_NAMES: AxisName[] = ['roll', 'pitch', 'yaw', 'throttle'];

export const DEFAULT_MAPPING: Mapping = {
  roll: { src: 'in:roll', rev: false }, pitch: { src: 'in:pitch', rev: false },
  yaw: { src: 'in:yaw', rev: false }, throttle: { src: 'in:throttle', rev: false },
  arm: { src: 'in:arm', thr: 0, dir: 1 }, flip: null,
};

const INPUTS = ['roll', 'pitch', 'yaw', 'throttle', 'arm', 'crash'];
export const ALL_SOURCES: Src[] = [...INPUTS.map((n) => `in:${n}`), ...Array.from({ length: 16 }, (_, i) => `ch:${i + 1}`)];
export const SWITCH_SOURCES: Src[] = [...ALL_SOURCES.filter((s) => s === 'in:arm' || s === 'in:crash'), ...ALL_SOURCES.filter((s) => s.startsWith('ch:'))];

export const srcLabel = (s: Src) => {
  if (s.startsWith('ch:')) { const n = Number(s.slice(3)); return n > 4 ? `CH${n} (AUX${n - 4})` : `CH${n}`; }
  return ({ 'in:roll': 'Stick: Ail', 'in:pitch': 'Stick: Ele', 'in:yaw': 'Stick: Rud', 'in:throttle': 'Stick: Thr',
    'in:arm': 'Radio ch5 (default ARM)', 'in:crash': 'Radio ch8 (default flip)' } as Record<string, string>)[s] ?? s;
};

/** Raw value (about -1024..1024) of a source in a bridge snapshot, or null when unavailable. */
export function rawOf(state: any, src: Src): number | null {
  if (!state) return null;
  if (src.startsWith('ch:')) { const v = state.channels?.[Number(src.slice(3)) - 1]; return typeof v === 'number' ? v : null; }
  const v = state.raw?.[src.slice(3)];
  return typeof v === 'number' ? v : null;
}

export const norm = (raw: number) => Math.max(-1, Math.min(1, raw / 1024));
export const switchActive = (raw: number, m: SwitchMap) => (m.dir === 1 ? raw > m.thr : raw < m.thr);

export interface Mapped {
  live: boolean; roll: number; pitch: number; yaw: number; throttle: number; // axes -1..1, throttle 0..1
  arm: boolean | null; flip: boolean | null;
}

export function applyMapping(state: any, m: Mapping): Mapped {
  const axis = (a: AxisMap) => { const v = rawOf(state, a.src); return v === null ? null : norm(v) * (a.rev ? -1 : 1); };
  const roll = axis(m.roll), pitch = axis(m.pitch), yaw = axis(m.yaw), thr = axis(m.throttle);
  const sw = (s: SwitchMap | null) => { if (!s) return null; const v = rawOf(state, s.src); return v === null ? null : switchActive(v, s); };
  const live = !!state?.controls && ['live', 'demo'].includes(state.status) && [roll, pitch, yaw, thr].every((v) => v !== null);
  if (!live) return { live: false, roll: 0, pitch: 0, yaw: 0, throttle: 0, arm: null, flip: null };
  return { live, roll: roll!, pitch: pitch!, yaw: yaw!, throttle: Math.max(0, Math.min(1, (thr! + 1) / 2)), arm: sw(m.arm), flip: sw(m.flip) };
}

/** Merge untrusted JSON onto a base mapping; anything invalid keeps the base value. */
export function cleanMapping(raw: any, base: Mapping): Mapping {
  const out: Mapping = JSON.parse(JSON.stringify(base));
  if (!raw || typeof raw !== 'object') return out;
  for (const a of AXIS_NAMES) {
    const m = raw[a];
    if (m && ALL_SOURCES.includes(m.src)) out[a] = { src: m.src, rev: m.rev === true };
  }
  for (const k of ['arm', 'flip'] as const) {
    if (!(k in raw)) continue;
    const m = raw[k];
    if (m === null) out[k] = null;
    else if (m && ALL_SOURCES.includes(m.src) && (m.dir === 1 || m.dir === -1) && Number.isFinite(m.thr)) out[k] = { src: m.src, thr: Math.round(m.thr), dir: m.dir };
  }
  return out;
}

export interface LearnResult { src: Src; base: number; level: number }

/**
 * Detects which source the user moves. Call update() with every snapshot. The first call records the resting
 * values; once something moved by TRIGGER the learner waits SETTLE ms for the biggest mover, then reports it.
 * Sources that were already moving (noise) are ignored via the baseline.
 */
export class Learner {
  static TRIGGER = 600; // raw units, about 30 % of full travel
  static SETTLE = 350; // ms
  private base = new Map<Src, number>();
  private best = new Map<Src, { delta: number; level: number }>();
  private triggeredAt: number | null = null;
  private candidates: Src[];
  constructor(candidates: Src[]) { this.candidates = candidates; }

  update(state: any, now: number): LearnResult | null {
    for (const src of this.candidates) {
      const v = rawOf(state, src);
      if (v === null) continue;
      if (!this.base.has(src)) { this.base.set(src, v); continue; }
      const delta = v - this.base.get(src)!;
      const prev = this.best.get(src);
      if (!prev || Math.abs(delta) > Math.abs(prev.delta)) this.best.set(src, { delta, level: v });
      if (this.triggeredAt === null && Math.abs(delta) >= Learner.TRIGGER) this.triggeredAt = now;
    }
    if (this.triggeredAt === null || now - this.triggeredAt < Learner.SETTLE) return null;
    // Biggest mover wins; stick inputs beat the channel that merely mirrors them (a tie within 10 %).
    let pick: Src | null = null, size = 0;
    for (const [src, b] of this.best) {
      const mag = Math.abs(b.delta);
      if (mag > size * 1.1 || (pick !== null && mag >= size * 0.9 && src.startsWith('in:') && !pick.startsWith('in:'))) { pick = src; size = mag; }
    }
    return pick ? { src: pick, base: this.base.get(pick)!, level: this.best.get(pick)!.level } : null;
  }

  /** Live feedback while waiting: the source that has moved most so far. */
  leader(): { src: Src; delta: number } | null {
    let pick: Src | null = null, size = 0;
    for (const [src, b] of this.best) if (Math.abs(b.delta) > size) { pick = src; size = Math.abs(b.delta); }
    return pick ? { src: pick, delta: this.best.get(pick)!.delta } : null;
  }
}

export const axisFromLearn = (r: LearnResult): AxisMap => ({ src: r.src, rev: r.level < r.base });
export const switchFromLearn = (r: LearnResult): SwitchMap => ({ src: r.src, thr: Math.round((r.base + r.level) / 2), dir: r.level > r.base ? 1 : -1 });
