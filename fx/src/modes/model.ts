// The list of mode cards on the Modes page, and the edits that can be made to the configuration. Pure: every edit returns a new object.
import { type Range } from './scale.ts';

export interface Mode { scene: string; ranges: Range[] }
export interface WhenNone { action: 'stay' | 'previous' | 'scene'; scene: string | null }
export interface SceneModes { enabled: boolean; debounceMs: number; whenNone: WhenNone; modes: Mode[] }

export interface Card { scene: string; ranges: Range[]; used: boolean; inObs: boolean | null; priority: number | null }

/**
 * The cards to show. Modes that have ranges come first, in priority order; with `hideUnused` off the scenes without ranges follow
 * in OBS order (so a first-time user sees every scene with an "Add Range" button). `obsScenes` null = OBS not connected: unknown.
 */
export function buildCards(cfg: SceneModes, obsScenes: string[] | null, hideUnused: boolean): Card[] {
  const known = obsScenes === null ? null : new Set(obsScenes);
  const used: Card[] = cfg.modes.filter((m) => m.ranges.length).map((m, i) => ({ scene: m.scene, ranges: m.ranges, used: true, inObs: known ? known.has(m.scene) : null, priority: i + 1 }));
  if (hideUnused || !obsScenes) return used;
  const have = new Set(used.map((c) => c.scene));
  return [...used, ...obsScenes.filter((s) => !have.has(s)).map((s): Card => ({ scene: s, ranges: [], used: false, inObs: true, priority: null }))];
}

const copy = (cfg: SceneModes): SceneModes => JSON.parse(JSON.stringify(cfg));
const find = (cfg: SceneModes, scene: string) => cfg.modes.find((m) => m.scene === scene);
/** A mode with no ranges is the same as no mode: drop it so the stored list only holds what is in use. */
const tidy = (cfg: SceneModes): SceneModes => ({ ...cfg, modes: cfg.modes.filter((m) => m.ranges.length) });

export const DEFAULT_RANGE: Range = { channel: 'ch:5', min: 1700, max: 2100 };

export function addRange(cfg: SceneModes, scene: string, range: Range = DEFAULT_RANGE): SceneModes {
  const c = copy(cfg), m = find(c, scene);
  if (m) { if (m.ranges.length < 8) m.ranges.push({ ...range }); }
  else c.modes.push({ scene, ranges: [{ ...range }] }); // a newly used scene starts with the lowest priority
  return c;
}

export function setRange(cfg: SceneModes, scene: string, index: number, range: Range): SceneModes {
  const c = copy(cfg), m = find(c, scene);
  if (m && m.ranges[index]) m.ranges[index] = { ...range };
  return c;
}

export function removeRange(cfg: SceneModes, scene: string, index: number): SceneModes {
  const c = copy(cfg), m = find(c, scene);
  if (m) m.ranges.splice(index, 1);
  return tidy(c);
}

/** Move a mode up (-1, higher priority) or down (+1) in the list. */
export function moveMode(cfg: SceneModes, scene: string, direction: -1 | 1): SceneModes {
  const c = copy(cfg), i = c.modes.findIndex((m) => m.scene === scene), j = i + direction;
  if (i < 0 || j < 0 || j >= c.modes.length) return c;
  [c.modes[i], c.modes[j]] = [c.modes[j], c.modes[i]];
  return c;
}

/** Put a mode at position `to` in the priority list (0 = top, wins first); out-of-range positions are clamped. */
export function moveModeTo(cfg: SceneModes, scene: string, to: number): SceneModes {
  const c = copy(cfg), from = c.modes.findIndex((m) => m.scene === scene);
  if (from < 0) return c;
  const [m] = c.modes.splice(from, 1);
  c.modes.splice(Math.max(0, Math.min(c.modes.length, to)), 0, m);
  return c;
}

/** The scene the engine picks when several are active: the first one in the list. */
export const winner = (active: string[]): string | null => active[0] ?? null;

/** Scenes whose ranges contain the live value of their channel (what the engine calls "active"). */
export function activeScenes(cfg: SceneModes, usByChannel: Record<string, number | null | undefined>): string[] {
  return cfg.modes.filter((m) => m.ranges.some((r) => { const us = usByChannel[r.channel]; return us != null && us >= r.min && us <= r.max; })).map((m) => m.scene);
}

export const DEFAULT_MODES: SceneModes = { enabled: false, debounceMs: 150, whenNone: { action: 'stay', scene: null }, modes: [] };
