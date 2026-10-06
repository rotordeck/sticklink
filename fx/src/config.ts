// Overlay settings, shared by URL seeding, the server-stored config and the double-click panel.
import { DEFAULT_MAPPING, cleanMapping, type Mapping } from './mapping.ts';

export type Mode = 1 | 2 | 3 | 4;
export type HudLayout = 'corners' | 'row' | 'column';
export type MapProvider = 'osm' | 'carto-dark' | 'carto-light' | 'custom' | 'none';
export interface HudConfig {
  style: string | null; // null = follow the main style
  layout: HudLayout; cells: number;
  blocks: { link: boolean; battery: boolean; gps: boolean; status: boolean };
  units: { speed: 'kmh' | 'mph'; alt: 'm' | 'ft' };
  map: { provider: MapProvider; customUrl: string; attribution: string; zoom: 'auto' | number; follow: boolean };
}
export interface FxConfig {
  style: string; chaos: number; mode: Mode; delay: number;
  invert: string[]; size: number; mapping: Mapping; hud: HudConfig;
}

export const DEFAULT_HUD: HudConfig = {
  style: null, layout: 'corners', cells: 4,
  blocks: { link: true, battery: true, gps: true, status: true },
  units: { speed: 'kmh', alt: 'm' },
  map: { provider: 'osm', customUrl: '', attribution: '', zoom: 'auto', follow: true },
};
export const HUD_LAYOUTS: HudLayout[] = ['corners', 'row', 'column'];
export const MAP_PROVIDERS: MapProvider[] = ['osm', 'carto-dark', 'carto-light', 'custom', 'none'];
export const TILE_URL = /^(https:\/\/|http:\/\/(localhost|127\.0\.0\.1)(:\d{1,5})?\/)[^\s"'<>]{1,250}$/;

export const DEFAULTS: FxConfig = { style: 'neon', chaos: 1, mode: 2, delay: 0, invert: [], size: 1080, mapping: DEFAULT_MAPPING, hud: DEFAULT_HUD };
export const AXES = ['roll', 'pitch', 'yaw', 'throttle'];

const num = (v: unknown, lo: number, hi: number, fb: number) => {
  const n = typeof v === 'string' && v.trim() === '' ? NaN : Number(v);
  return Number.isFinite(n) ? Math.max(lo, Math.min(hi, n)) : fb;
};

const bool = (v: unknown, fb: boolean) => (typeof v === 'boolean' ? v : fb);

/** Validate the HUD settings (untrusted input); anything invalid keeps the base value. */
export function cleanHud(raw: any, base: HudConfig, styles: string[]): HudConfig {
  const out: HudConfig = JSON.parse(JSON.stringify(base));
  if (!raw || typeof raw !== 'object') return out;
  if (raw.style === null || (typeof raw.style === 'string' && styles.includes(raw.style))) out.style = raw.style;
  if (HUD_LAYOUTS.includes(raw.layout)) out.layout = raw.layout;
  if ('cells' in raw) out.cells = Math.round(num(raw.cells, 1, 8, base.cells));
  if (raw.blocks && typeof raw.blocks === 'object') {
    for (const k of Object.keys(out.blocks) as (keyof HudConfig['blocks'])[]) out.blocks[k] = bool(raw.blocks[k], out.blocks[k]);
  }
  if (raw.units && typeof raw.units === 'object') {
    if (raw.units.speed === 'kmh' || raw.units.speed === 'mph') out.units.speed = raw.units.speed;
    if (raw.units.alt === 'm' || raw.units.alt === 'ft') out.units.alt = raw.units.alt;
  }
  const m = raw.map;
  if (m && typeof m === 'object') {
    if (MAP_PROVIDERS.includes(m.provider)) out.map.provider = m.provider;
    if (typeof m.customUrl === 'string' && (m.customUrl === '' || (TILE_URL.test(m.customUrl) && ['{z}', '{x}', '{y}'].every((t) => m.customUrl.includes(t))))) out.map.customUrl = m.customUrl;
    if (typeof m.attribution === 'string' && m.attribution.length <= 120 && !/[<>\r\n\t]/.test(m.attribution)) out.map.attribution = m.attribution;
    if (m.zoom === 'auto') out.map.zoom = 'auto';
    else if ('zoom' in m && Number.isFinite(Number(m.zoom))) out.map.zoom = Math.round(num(m.zoom, 1, 19, 15));
    out.map.follow = bool(m.follow, out.map.follow);
  }
  return out;
}

/** Validate untrusted input (URL, server JSON, form); unknown or invalid keys fall back to `base`. */
export function clean(raw: Record<string, unknown>, base: FxConfig, styles: string[]): FxConfig {
  const out = { ...base };
  if (typeof raw.style === 'string' && styles.includes(raw.style)) out.style = raw.style;
  if ('chaos' in raw) out.chaos = num(raw.chaos, 0, 2, base.chaos);
  if ('mode' in raw) { const m = Number(raw.mode); out.mode = (m === 1 || m === 3 || m === 4 ? m : 2) as Mode; }
  if ('delay' in raw) out.delay = Math.round(num(raw.delay, 0, 5000, base.delay));
  if ('mapping' in raw) out.mapping = cleanMapping(raw.mapping, base.mapping);
  if ('hud' in raw) out.hud = cleanHud(raw.hud, base.hud, styles);
  if ('invert' in raw) {
    const list = Array.isArray(raw.invert) ? raw.invert : String(raw.invert ?? '').split(',');
    out.invert = AXES.filter((a) => list.includes(a));
  }
  if ('size' in raw) out.size = Math.round(num(raw.size, 240, 2160, base.size));
  return out;
}
