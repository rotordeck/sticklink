// Permanent links: a configuration packed into one URL parameter, so a look can be shared or bookmarked.
// The link holds only what differs from the defaults (so it stays short and survives new defaults), as versioned base64url JSON.
// Opening it reproduces that configuration regardless of what is saved on the server. Pure: no DOM.
import { DEFAULTS, type FxConfig } from './config.ts';

export const PARAM = 'cfg';
export const VERSION = 'v1';
export const MAX_PARAM_LENGTH = 8192;

/** What each kind of page keeps in its link (the HUD pages do not need the stick-overlay settings, and vice versa). */
export type Scope = 'fx' | 'hud';
export const SCOPE_KEYS: Record<Scope, (keyof FxConfig)[]> = {
  fx: ['style', 'chaos', 'mode', 'delay', 'invert', 'size', 'mapping'],
  hud: ['style', 'mapping', 'hud'],
};

const isObject = (v: unknown): v is Record<string, unknown> => typeof v === 'object' && v !== null && !Array.isArray(v);

/** The parts of `value` that differ from `base` (deeply, for objects); undefined when nothing differs. */
export function diff(value: unknown, base: unknown): unknown {
  if (isObject(value) && isObject(base)) {
    const out: Record<string, unknown> = {};
    for (const key of Object.keys(value)) {
      const d = diff(value[key], base[key]);
      if (d !== undefined) out[key] = d;
    }
    return Object.keys(out).length ? out : undefined;
  }
  return JSON.stringify(value) === JSON.stringify(base) ? undefined : value;
}

function toBase64Url(text: string): string {
  const bytes = new TextEncoder().encode(text);
  let bin = '';
  for (const b of bytes) bin += String.fromCharCode(b);
  return btoa(bin).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

function fromBase64Url(text: string): string {
  const bin = atob(text.replace(/-/g, '+').replace(/_/g, '/'));
  return new TextDecoder('utf-8', { fatal: true }).decode(Uint8Array.from(bin, (c) => c.charCodeAt(0)));
}

/** The parameter value for a configuration: version, a dot, base64url of the JSON difference from the defaults. */
export function encodeConfig(cfg: FxConfig, scope: Scope): string {
  const part: Record<string, unknown> = {};
  for (const key of SCOPE_KEYS[scope]) {
    const d = diff(cfg[key], DEFAULTS[key]);
    if (d !== undefined) part[key] = d;
  }
  return `${VERSION}.${toBase64Url(JSON.stringify(part))}`;
}

/** The raw (still untrusted) settings in a parameter value, or null if it is missing, too long, or not a valid v1 link. */
export function decodeConfig(param: string | null | undefined): Record<string, unknown> | null {
  if (!param || param.length > MAX_PARAM_LENGTH || !param.startsWith(`${VERSION}.`)) return null;
  try {
    const parsed = JSON.parse(fromBase64Url(param.slice(VERSION.length + 1)));
    return isObject(parsed) ? parsed : null;
  } catch { return null; }
}

/** The permanent URL of this page for a configuration. The caller passes `location`'s origin and pathname. */
export function permalink(origin: string, pathname: string, cfg: FxConfig, scope: Scope): string {
  return `${origin}${pathname}?${PARAM}=${encodeConfig(cfg, scope)}`;
}
