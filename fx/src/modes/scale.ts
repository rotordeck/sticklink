// The microsecond scale of the Modes page (Betaflight's 900-2100 in 25 steps) and what a switch position means on it. Pure.

export const US_MIN = 900, US_MAX = 2100, STEP = 25;
/** Tick marks and labels under every slider, as in Betaflight's Modes tab. */
export const TICKS = [900, 1000, 1200, 1400, 1500, 1600, 1800, 2000, 2100];

export const clamp = (v: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, v));
export const snap = (us: number) => clamp(Math.round(us / STEP) * STEP, US_MIN, US_MAX);
export const usToFrac = (us: number) => (clamp(us, US_MIN, US_MAX) - US_MIN) / (US_MAX - US_MIN);
export const fracToUs = (f: number) => snap(US_MIN + clamp(f, 0, 1) * (US_MAX - US_MIN));

/** EdgeTX channel value (-1024..1024) as microseconds (1000..2000 at the ends), like the server computes it. */
export const rawToUs = (raw: number) => Math.round(1500 + (raw * 500) / 1024);

export interface Range { channel: string; min: number; max: number }

/** Move one handle to `us`, keeping min <= max (the handle stops at the other one) and the 25 us grid. */
export function moveHandle(range: Range, handle: 'min' | 'max', us: number): Range {
  const v = snap(us);
  return handle === 'min' ? { ...range, min: Math.min(v, range.max) } : { ...range, max: Math.max(v, range.min) };
}

/** A range for the position a switch was just put in: low, middle or high third, like a 3-position switch's usual zones. */
export function rangeForPosition(channel: string, us: number): Range {
  if (us < 1250) return { channel, min: 900, max: 1300 };
  if (us <= 1750) return { channel, min: 1300, max: 1700 };
  return { channel, min: 1700, max: 2100 };
}

export const inRange = (us: number | null | undefined, r: Range) => us != null && us >= r.min && us <= r.max;

/** Betaflight calls channel 5 "AUX 1". Channels 1-4 are the sticks and are not offered. */
export const AUX_CHANNELS = Array.from({ length: 12 }, (_, i) => `ch:${i + 5}`);
export const auxLabel = (channel: string) => { const n = Number(channel.slice(3)); return n >= 5 ? `AUX ${n - 4}` : `CH ${n}`; };
