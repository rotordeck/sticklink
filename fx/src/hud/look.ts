// A stickcam Style turned into HUD drawing helpers: badge plates and frames, text, bars, dials, sparklines, scanlines.
// Everything is drawn in design units (the caller scales the canvas), so sizes here are not pixels.
import { parseColor } from '../render/draw.ts';
import type { Style } from '../render/style.ts';
import type { Level } from './catalog.ts';

export type Ctx = CanvasRenderingContext2D;
export const WARN = '#ffb347', CRIT = '#ff4d4d';

export interface Look {
  style: Style;
  t: number; // seconds, for animation
  accent: string; hot: string; text: string; stroke: string; muted: string; plate: string; ring: string;
  glow: number; // shadow blur in design units
  font(px: number, weight?: string): string;
  levelColor(level: Level): string;
}

const rgba = (c: [number, number, number, number], a = 1) => `rgba(${c[0] | 0},${c[1] | 0},${c[2] | 0},${Math.max(0, Math.min(1, c[3] * a)).toFixed(3)})`;
const hsl = (h: number, a = 1, l = 62) => `hsla(${(h % 360).toFixed(0)},100%,${l}%,${a})`;

export function makeLook(style: Style, t: number): Look {
  const accent = style.rainbow ? hsl(t * 70) : style.dot;
  const hot = style.rainbow ? hsl(t * 70 + 120) : style.hot ?? style.dot;
  const ring = style.ring === 'rainbow' ? hsl(t * 70 + 200) : style.ring;
  const text = style.textColor, muted = rgba(parseColor(text), 0.55);
  const look: Look = {
    style, t, accent, hot, text, stroke: style.textStroke, muted, ring,
    plate: style.plate ?? 'rgba(0,0,0,0.30)',
    glow: (style.glow + style.bloom * 0.5) * 16,
    font: (px, weight = '') => `${weight} ${style.font.replace('{px}', px.toFixed(1))}`.trim(),
    levelColor: (level) => (level === 'warn' ? WARN : level === 'crit' ? CRIT : level === 'off' ? muted : accent),
  };
  return look;
}

/** The frame shape follows the style: brackets (hacker), clipped corners (square styles), rounded (circle styles), none. */
export function framePath(ctx: Ctx, x: number, y: number, w: number, h: number, look: Look, cut = 14) {
  ctx.beginPath();
  const f = look.style.frame;
  if (f === 'circle') {
    const r = Math.min(cut * 1.6, w / 2, h / 2);
    ctx.roundRect(x, y, w, h, r);
  } else {
    ctx.moveTo(x + cut, y); ctx.lineTo(x + w - cut, y); ctx.lineTo(x + w, y + cut); ctx.lineTo(x + w, y + h - cut);
    ctx.lineTo(x + w - cut, y + h); ctx.lineTo(x + cut, y + h); ctx.lineTo(x, y + h - cut); ctx.lineTo(x, y + cut); ctx.closePath();
  }
}

export function brackets(ctx: Ctx, x: number, y: number, w: number, h: number, len: number) {
  ctx.beginPath();
  for (const [cx, cy, dx, dy] of [[x, y, 1, 1], [x + w, y, -1, 1], [x, y + h, 1, -1], [x + w, y + h, -1, -1]]) {
    ctx.moveTo(cx + dx * len, cy); ctx.lineTo(cx, cy); ctx.lineTo(cx, cy + dy * len);
  }
}

/** A block's plate: translucent fill and an outline in the style's shape, with a glow if the style has one. */
export function plate(ctx: Ctx, x: number, y: number, w: number, h: number, look: Look, tone?: string) {
  const frame = look.style.frame, color = tone ?? look.ring;
  ctx.save();
  framePath(ctx, x, y, w, h, look);
  ctx.fillStyle = look.plate; ctx.fill();
  if (frame !== 'none') {
    ctx.lineWidth = Math.max(1.5, look.style.ringW * 40);
    ctx.strokeStyle = color;
    if (look.glow > 0) { ctx.shadowColor = color; ctx.shadowBlur = look.glow; }
    if (frame === 'brackets') { brackets(ctx, x, y, w, h, Math.min(26, w / 5, h / 5)); ctx.stroke(); }
    else { framePath(ctx, x, y, w, h, look); ctx.stroke(); }
  }
  ctx.restore();
}

export type Align = 'left' | 'center' | 'right';

export function text(ctx: Ctx, s: string, x: number, y: number, px: number, look: Look,
  opts: { align?: Align; color?: string; alpha?: number; weight?: string; glow?: boolean; stroke?: boolean; base?: CanvasTextBaseline } = {}) {
  ctx.save();
  ctx.font = look.font(px, opts.weight); ctx.textAlign = opts.align ?? 'left'; ctx.textBaseline = opts.base ?? 'alphabetic';
  ctx.globalAlpha = opts.alpha ?? 1;
  if (opts.stroke !== false) { ctx.lineWidth = Math.max(1, px * 0.12); ctx.strokeStyle = look.stroke; ctx.lineJoin = 'round'; ctx.strokeText(s, x, y); }
  ctx.fillStyle = opts.color ?? look.text;
  if (opts.glow && look.glow > 0) { ctx.shadowColor = opts.color ?? look.accent; ctx.shadowBlur = look.glow * 0.8; }
  ctx.fillText(s, x, y);
  ctx.restore();
}

export const label = (ctx: Ctx, s: string, x: number, y: number, look: Look, align: Align = 'left', px = 15) =>
  text(ctx, s, x, y, px, look, { align, color: look.muted, stroke: false });

/** Big value with a small unit next to it; returns the width used so callers can place things after it. */
export function value(ctx: Ctx, s: string, unit: string, x: number, y: number, px: number, color: string, look: Look, align: Align = 'left') {
  ctx.save(); ctx.font = look.font(px);
  const vw = ctx.measureText(s).width; ctx.font = look.font(px * 0.42);
  const uw = unit ? ctx.measureText(unit).width + px * 0.14 : 0;
  ctx.restore();
  const total = vw + uw, x0 = align === 'left' ? x : align === 'center' ? x - total / 2 : x - total;
  text(ctx, s, x0, y, px, look, { color, glow: true });
  if (unit) text(ctx, unit, x0 + vw + px * 0.14, y, px * 0.42, look, { color: look.muted, stroke: false });
  return total;
}

export function bar(ctx: Ctx, x: number, y: number, w: number, h: number, frac: number | null, color: string, look: Look, segments = 0) {
  ctx.save();
  ctx.fillStyle = 'rgba(255,255,255,0.10)'; ctx.fillRect(x, y, w, h);
  if (frac !== null) {
    ctx.fillStyle = color;
    if (look.glow > 0) { ctx.shadowColor = color; ctx.shadowBlur = look.glow * 0.5; }
    ctx.fillRect(x, y, w * Math.max(0, Math.min(1, frac)), h);
  }
  if (segments > 1) { // cell ticks, drawn over the fill
    ctx.fillStyle = 'rgba(0,0,0,0.55)';
    for (let i = 1; i < segments; i++) ctx.fillRect(x + (w * i) / segments - 1, y, 2, h);
  }
  ctx.restore();
}

/** A 270 degree dial; the gap is at the bottom. */
export function dial(ctx: Ctx, cx: number, cy: number, r: number, frac: number | null, color: string, look: Look, lw = 14) {
  const a0 = Math.PI * 0.75, span = Math.PI * 1.5;
  ctx.save(); ctx.lineCap = 'round'; ctx.lineWidth = lw;
  ctx.strokeStyle = 'rgba(255,255,255,0.12)'; ctx.beginPath(); ctx.arc(cx, cy, r, a0, a0 + span); ctx.stroke();
  if (frac !== null && frac > 0) {
    ctx.strokeStyle = color;
    if (look.glow > 0) { ctx.shadowColor = color; ctx.shadowBlur = look.glow; }
    ctx.beginPath(); ctx.arc(cx, cy, r, a0, a0 + span * Math.max(0.005, Math.min(1, frac))); ctx.stroke();
  }
  ctx.restore();
}

export function sparkline(ctx: Ctx, x: number, y: number, w: number, h: number, series: readonly number[], color: string, look: Look,
  range?: [number, number]) {
  ctx.save();
  ctx.strokeStyle = 'rgba(255,255,255,0.10)'; ctx.lineWidth = 1;
  ctx.beginPath(); ctx.moveTo(x, y + h); ctx.lineTo(x + w, y + h); ctx.stroke();
  if (series.length > 1) {
    const lo = range ? range[0] : Math.min(...series), hi = range ? range[1] : Math.max(...series), span = hi - lo || 1;
    ctx.strokeStyle = color; ctx.lineWidth = 2.5; ctx.lineJoin = 'round';
    if (look.glow > 0) { ctx.shadowColor = color; ctx.shadowBlur = look.glow * 0.5; }
    ctx.beginPath();
    series.forEach((v, i) => {
      const px = x + (i / Math.max(1, series.length - 1)) * w, py = y + h - Math.max(0, Math.min(1, (v - lo) / span)) * h;
      if (i) ctx.lineTo(px, py); else ctx.moveTo(px, py);
    });
    ctx.stroke();
  }
  ctx.restore();
}

/** Blink factor for critical states (0.45..1), steady for everything else. */
export const pulse = (look: Look, level: Level) => (level === 'crit' ? 0.7 + 0.3 * Math.sin(look.t * 9) : 1);

export function scanlines(ctx: Ctx, w: number, h: number, look: Look, scale: number) {
  const s = look.style.scan;
  if (s <= 0) return;
  ctx.save();
  ctx.fillStyle = `rgba(0,0,0,${(0.28 * s).toFixed(3)})`;
  const step = Math.max(3, 3 * scale);
  for (let y = 0; y < h; y += step) ctx.fillRect(0, y, w, Math.max(1, step / 3));
  ctx.restore();
}

/** Largest font size (down to `min`) at which `s` fits in `maxWidth`. */
export function fitPx(ctx: Ctx, s: string, maxWidth: number, px: number, look: Look, min = 9): number {
  ctx.save();
  let p = px;
  for (; p > min; p -= 0.5) { ctx.font = look.font(p); if (ctx.measureText(s).width <= maxWidth) break; }
  ctx.restore();
  return p;
}
