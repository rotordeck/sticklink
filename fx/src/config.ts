// Overlay settings, shared by URL seeding, the server-stored config and the double-click panel.
import { DEFAULT_MAPPING, cleanMapping, type Mapping } from './mapping.ts';

export type Mode = 1 | 2 | 3 | 4;
export interface FxConfig {
  style: string; chaos: number; mode: Mode; delay: number;
  invert: string[]; size: number; mapping: Mapping;
}

export const DEFAULTS: FxConfig = { style: 'neon', chaos: 1, mode: 2, delay: 0, invert: [], size: 1080, mapping: DEFAULT_MAPPING };
export const AXES = ['roll', 'pitch', 'yaw', 'throttle'];

const num = (v: unknown, lo: number, hi: number, fb: number) => {
  const n = typeof v === 'string' && v.trim() === '' ? NaN : Number(v);
  return Number.isFinite(n) ? Math.max(lo, Math.min(hi, n)) : fb;
};

/** Validate untrusted input (URL, server JSON, form); unknown or invalid keys fall back to `base`. */
export function clean(raw: Record<string, unknown>, base: FxConfig, styles: string[]): FxConfig {
  const out = { ...base };
  if (typeof raw.style === 'string' && styles.includes(raw.style)) out.style = raw.style;
  if ('chaos' in raw) out.chaos = num(raw.chaos, 0, 2, base.chaos);
  if ('mode' in raw) { const m = Number(raw.mode); out.mode = (m === 1 || m === 3 || m === 4 ? m : 2) as Mode; }
  if ('delay' in raw) out.delay = Math.round(num(raw.delay, 0, 5000, base.delay));
  if ('mapping' in raw) out.mapping = cleanMapping(raw.mapping, base.mapping);
  if ('invert' in raw) {
    const list = Array.isArray(raw.invert) ? raw.invert : String(raw.invert ?? '').split(',');
    out.invert = AXES.filter((a) => list.includes(a));
  }
  if ('size' in raw) out.size = Math.round(num(raw.size, 240, 2160, base.size));
  return out;
}
