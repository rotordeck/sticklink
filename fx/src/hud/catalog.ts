// Turns the bridge's telemetry into HUD badge models: names, units, bar fractions and ok/warn/crit states.
// Pure functions; the drawing code only renders what these return. Sensor names are the ones EdgeTX shows.
import { bearing, formatDistance, haversine, type LatLon } from './geo.ts';

export type Level = 'ok' | 'warn' | 'crit' | 'off';
export interface Sensor { value: number; current: boolean; fresh: boolean; age_ms: number }
export type Telemetry = Record<string, Sensor>;
export interface Units { speed: 'kmh' | 'mph'; alt: 'm' | 'ft' }

export interface Badge {
  id: string; label: string; text: string; unit: string;
  frac: number | null; // 0..1 for a bar, null = no bar
  level: Level; value: number | null;
}

interface Info {
  label: string; unit: string; dec: number;
  range?: [number, number]; // bar scale
  ok?: number; warn?: number; // thresholds; higher is better
  conv?: 'speed' | 'alt' | 'deg'; // unit conversion
}

const INFO: Record<string, Info> = {
  RQly: { label: 'LINK', unit: '%', dec: 0, range: [0, 100], ok: 80, warn: 60 },
  RSNR: { label: 'SNR', unit: 'dB', dec: 0, range: [-20, 20], ok: 5, warn: 0 },
  '1RSS': { label: 'RSSI A', unit: 'dBm', dec: 0, range: [-120, -30], ok: -85, warn: -100 },
  '2RSS': { label: 'RSSI B', unit: 'dBm', dec: 0, range: [-120, -30], ok: -85, warn: -100 },
  TPWR: { label: 'TX POWER', unit: 'mW', dec: 0 },
  RFMD: { label: 'RF MODE', unit: '', dec: 0 },
  ANT: { label: 'ANTENNA', unit: '', dec: 0 },
  TRSS: { label: 'UP RSSI', unit: 'dBm', dec: 0, range: [-120, -30], ok: -85, warn: -100 },
  TQly: { label: 'UP LINK', unit: '%', dec: 0, range: [0, 100], ok: 80, warn: 60 },
  TSNR: { label: 'UP SNR', unit: 'dB', dec: 0, range: [-20, 20], ok: 5, warn: 0 },
  RxBt: { label: 'PACK', unit: 'V', dec: 2 },
  Curr: { label: 'CURRENT', unit: 'A', dec: 1 },
  Capa: { label: 'USED', unit: 'mAh', dec: 0 },
  'Bat%': { label: 'REMAINING', unit: '%', dec: 0, range: [0, 100], ok: 30, warn: 15 },
  Sats: { label: 'SATS', unit: '', dec: 0, range: [0, 20], ok: 8, warn: 5 },
  GSpd: { label: 'SPEED', unit: 'km/h', dec: 0, conv: 'speed' },
  GAlt: { label: 'ALT', unit: 'm', dec: 0, conv: 'alt' },
  Alt: { label: 'ALT', unit: 'm', dec: 0, conv: 'alt' },
  VSpd: { label: 'CLIMB', unit: 'm/s', dec: 1 },
  Hdg: { label: 'HEADING', unit: '°', dec: 0 },
  Ptch: { label: 'PITCH', unit: '°', dec: 0, conv: 'deg' }, // EdgeTX reports attitude in radians
  Roll: { label: 'ROLL', unit: '°', dec: 0, conv: 'deg' },
  Yaw: { label: 'YAW', unit: '°', dec: 0, conv: 'deg' },
};

export const LINK_SENSORS = ['RQly', 'RSNR', '1RSS', '2RSS', 'TPWR', 'RFMD', 'ANT', 'TRSS', 'TQly', 'TSNR'];
export const BATTERY_SENSORS = ['RxBt', 'Curr', 'Capa', 'Bat%'];
export const GPS_SENSORS = ['Sats', 'GSpd', 'GAlt', 'Alt', 'VSpd', 'Hdg'];
export const ATTITUDE_SENSORS = ['Ptch', 'Roll', 'Yaw'];

const clamp01 = (v: number) => Math.max(0, Math.min(1, v));

export function levelOf(value: number, info: Pick<Info, 'ok' | 'warn'>): Level {
  if (info.ok === undefined || info.warn === undefined) return 'ok';
  return value >= info.ok ? 'ok' : value >= info.warn ? 'warn' : 'crit';
}

/** A badge for one sensor, or null if it was never received. A sensor that stopped updating shows as "off". */
export function badge(name: string, tel: Telemetry, units: Units): Badge | null {
  const s = tel[name];
  if (!s) return null;
  const info = INFO[name] ?? { label: name.toUpperCase(), unit: '', dec: 1 };
  let value = s.value, unit = info.unit;
  if (info.conv === 'speed' && units.speed === 'mph') { value *= 0.621371; unit = 'mph'; }
  if (info.conv === 'alt' && units.alt === 'ft') { value *= 3.28084; unit = 'ft'; }
  if (info.conv === 'deg') value = (value * 180) / Math.PI;
  const live = s.current;
  return {
    id: name, label: info.label, unit, value: live ? value : null,
    text: live ? value.toFixed(info.dec) : '—',
    frac: live && info.range ? clamp01((s.value - info.range[0]) / (info.range[1] - info.range[0])) : null,
    level: live ? levelOf(s.value, info) : 'off',
  };
}

const present = (names: string[], tel: Telemetry, units: Units) => names.map((n) => badge(n, tel, units)).filter((b): b is Badge => b !== null);

export interface LinkModel { present: boolean; quality: Badge | null; signal: Badge[]; radio: Badge[]; uplink: Badge[] }

export function buildLink(tel: Telemetry, units: Units): LinkModel {
  const all = present(LINK_SENSORS, tel, units), pick = (ids: string[]) => all.filter((b) => ids.includes(b.id));
  return { present: all.length > 0, quality: all.find((b) => b.id === 'RQly') ?? null, signal: pick(['RSNR', '1RSS', '2RSS']),
    radio: pick(['TPWR', 'RFMD', 'ANT']), uplink: pick(['TRSS', 'TQly', 'TSNR']) };
}

export interface BatteryModel {
  present: boolean; volts: number | null; perCell: number | null; level: Level; frac: number | null;
  current: Badge | null; used: Badge | null; percent: Badge | null; watts: number | null;
}

/** Per-cell thresholds are for LiPo/LiHV under load: 3.7 V and up is fine, under 3.5 V is a warning, under 3.3 V is critical. */
export function cellLevel(perCell: number): Level { return perCell >= 3.5 ? 'ok' : perCell >= 3.3 ? 'warn' : 'crit'; }

export function buildBattery(tel: Telemetry, cells: number, units: Units): BatteryModel {
  const pack = tel.RxBt, live = !!pack?.current && pack.value > 0;
  const volts = live ? pack.value : null, perCell = volts === null ? null : volts / Math.max(1, cells);
  const current = badge('Curr', tel, units);
  return {
    present: !!pack || present(BATTERY_SENSORS, tel, units).length > 0, volts, perCell,
    level: perCell === null ? 'off' : cellLevel(perCell),
    frac: perCell === null ? null : clamp01((perCell - 3.3) / (4.2 - 3.3)),
    current, used: badge('Capa', tel, units), percent: badge('Bat%', tel, units),
    watts: volts !== null && current?.value != null ? volts * current.value : null,
  };
}

export interface GpsInfo {
  fix: boolean; lat: number | null; lon: number | null; age_ms: number | null;
  home: LatLon | null; distance_m: number | null; bearing_deg: number | null; track_points?: number;
}
export interface GpsModel {
  present: boolean; fix: boolean; pos: LatLon | null; home: LatLon | null;
  distance: { text: string; unit: string } | null; bearing: number | null; homeDir: number | null;
  sats: Badge | null; speed: Badge | null; alt: Badge | null; heading: Badge | null; climb: Badge | null;
}

export function buildGps(gps: GpsInfo | null | undefined, tel: Telemetry, units: Units): GpsModel {
  const pos = gps && gps.lat !== null && gps.lon !== null ? { lat: gps.lat, lon: gps.lon } : null;
  const home = gps?.home ?? null;
  // Prefer the bridge's figures; recompute only if it sent a position without them.
  const dist = pos && home ? gps?.distance_m ?? haversine(home, pos) : null;
  const brg = pos && home ? gps?.bearing_deg ?? bearing(home, pos) : null;
  return {
    present: !!pos || present(GPS_SENSORS, tel, units).length > 0, fix: !!gps?.fix, pos, home,
    distance: dist === null ? null : formatDistance(dist, units.alt === 'ft'),
    bearing: brg, homeDir: brg === null ? null : (brg + 180) % 360,
    sats: badge('Sats', tel, units), speed: badge('GSpd', tel, units), alt: badge('GAlt', tel, units) ?? badge('Alt', tel, units),
    heading: badge('Hdg', tel, units), climb: badge('VSpd', tel, units),
  };
}

/** Sensors that belong to no block (so nothing the radio receives is silently dropped). */
export function others(tel: Telemetry, units: Units): Badge[] {
  const known = new Set([...LINK_SENSORS, ...BATTERY_SENSORS, ...GPS_SENSORS]);
  return Object.keys(tel).filter((n) => !known.has(n)).sort().map((n) => badge(n, tel, units)).filter((b): b is Badge => b !== null);
}

export function formatClock(seconds: number): string {
  const s = Math.max(0, Math.floor(seconds)), m = Math.floor(s / 60), h = Math.floor(m / 60);
  const pad = (n: number) => String(n).padStart(2, '0');
  return h ? `${h}:${pad(m % 60)}:${pad(s % 60)}` : `${pad(m)}:${pad(s % 60)}`;
}
