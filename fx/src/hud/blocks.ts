// The four HUD blocks, drawn in design units at (0, 0): Link, Battery, GPS (with the map) and Status.
import { badge, buildBattery, buildGps, buildLink, formatClock, type Badge, type GpsInfo, type Level, type Telemetry, type Units } from './catalog.ts';
import { PROVIDERS, mapView, project, type LatLon } from './geo.ts';
import type { HudConfig } from '../config.ts';
import type { History } from './history.ts';
import { bar, dial, fitPx, label, plate, pulse, sparkline, text, value, type Ctx, type Look } from './look.ts';
import { TileMap, drawTiles } from './map.ts';
import { DESIGN } from './layout.ts';

export type RadioState = 'live' | 'demo' | 'paused' | 'disconnected' | 'offline';

export interface HudData {
  tel: Telemetry; gps: GpsInfo | null; hud: HudConfig; units: Units;
  armSwitch: boolean; armed: boolean | null; flip: boolean | null; throttle: number | null; flightSeconds: number; radio: RadioState;
  track: LatLon[]; history: History; tiles: TileMap; now: number;
}

function noData(ctx: Ctx, w: number, h: number, what: string, look: Look) {
  text(ctx, what, w / 2, h / 2 + 6, 20, look, { align: 'center', color: look.muted, stroke: false });
}

// ---------------------------------------------------------------- Link
export function drawLink(ctx: Ctx, look: Look, d: HudData) {
  const { w, h } = DESIGN.link, link = buildLink(d.tel, d.units);
  plate(ctx, 0, 0, w, h, look);
  label(ctx, 'LINK', 22, 32, look);
  if (!link.present) return noData(ctx, w, h, 'NO LINK DATA', look);
  const q = link.quality, level: Level = q?.level ?? 'off', color = look.levelColor(level);
  ctx.save(); ctx.globalAlpha = pulse(look, level);
  dial(ctx, 100, 112, 56, q?.frac ?? null, color, look, 13);
  ctx.restore();
  text(ctx, q?.text ?? '—', 100, 124, 40, look, { align: 'center', color, glow: true });
  label(ctx, q ? 'QUALITY' : 'NO RQLY', 100, 176, look, 'center', 12);
  // signal rows
  link.signal.forEach((b, i) => {
    const y = 64 + i * 40, c = look.levelColor(b.level);
    label(ctx, b.label, 196, y, look, 'left', 14);
    value(ctx, b.text, b.unit, 378, y + 6, 24, c, look, 'right');
    bar(ctx, 196, y + 14, 182, 5, b.frac, c, look);
  });
  // history, then the radio and uplink details, each on one line that is shrunk to fit
  sparkline(ctx, 22, 192, 356, 28, d.history.series('RQly'), color, look, [0, 100]);
  const SHORT: Record<string, string> = { TPWR: 'TX', RFMD: 'RF', ANT: 'ANT', TRSS: 'UP', TQly: 'UP', TSNR: 'UP' };
  const chip = (b: Badge) => `${SHORT[b.id] ?? b.label} ${b.text}${b.unit && b.unit !== '%' ? b.unit : b.unit}`;
  const lines = [link.radio.map(chip).join('  ·  '), link.uplink.map(chip).join('  ·  ')].filter(Boolean);
  lines.forEach((line, i) => text(ctx, line, 22, 244 + i * 20, fitPx(ctx, line, 356, 14, look), look, { color: look.muted, stroke: false }));
}

// ---------------------------------------------------------------- Battery
export function drawBattery(ctx: Ctx, look: Look, d: HudData) {
  const { w, h } = DESIGN.battery, b = buildBattery(d.tel, d.hud.cells, d.units);
  plate(ctx, 0, 0, w, h, look);
  label(ctx, 'BATTERY', 22, 32, look);
  label(ctx, `${d.hud.cells}S`, 378, 32, look, 'right');
  if (!b.present) return noData(ctx, w, h, 'NO BATTERY DATA', look);
  const color = look.levelColor(b.level);
  ctx.save(); ctx.globalAlpha = pulse(look, b.level);
  value(ctx, b.volts === null ? '—' : b.volts.toFixed(2), 'V', 22, 92, 58, color, look);
  ctx.restore();
  text(ctx, b.perCell === null ? '' : `${b.perCell.toFixed(2)} V / cell`, 24, 116, 18, look, { color: look.muted, stroke: false });
  if (b.percent && b.percent.value !== null) {
    label(ctx, 'REMAINING', 378, 56, look, 'right', 13);
    value(ctx, b.percent.text, '%', 378, 96, 40, look.levelColor(b.percent.level), look, 'right');
  }
  bar(ctx, 22, 128, 356, 16, b.frac, color, look, d.hud.cells);
  const cols: [string, string, string][] = [
    ['CURRENT', b.current?.text ?? '—', 'A'], ['USED', b.used?.text ?? '—', 'mAh'], ['POWER', b.watts === null ? '—' : b.watts.toFixed(0), 'W'],
  ];
  cols.forEach(([lab, val, unit], i) => {
    const x = 22 + i * 120;
    label(ctx, lab, x, 172, look, 'left', 13);
    value(ctx, val, unit, x, 200, 28, look.text, look);
  });
  sparkline(ctx, 22, 214, 356, 24, d.history.series('RxBt'), color, look);
}

// ---------------------------------------------------------------- GPS
const NICE = [5, 10, 20, 50, 100, 200, 500, 1000, 2000, 5000, 10000, 20000, 50000];

function mapGrid(ctx: Ctx, w: number, h: number, look: Look) {
  ctx.save();
  ctx.strokeStyle = 'rgba(255,255,255,0.07)'; ctx.lineWidth = 1;
  for (let x = 0; x <= w; x += 40) { ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, h); ctx.stroke(); }
  for (let y = 0; y <= h; y += 40) { ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(w, y); ctx.stroke(); }
  ctx.strokeStyle = look.ring; ctx.globalAlpha = 0.12;
  for (const r of [60, 120, 180]) { ctx.beginPath(); ctx.arc(w / 2, h / 2, r, 0, Math.PI * 2); ctx.stroke(); }
  ctx.restore();
}

function resolveProvider(hud: HudConfig) {
  const m = hud.map;
  if (m.provider === 'none') return null;
  if (m.provider === 'custom') return m.customUrl ? { url: m.customUrl, subdomains: undefined, attribution: m.attribution || 'Custom map tiles', maxZoom: 19, darken: true } : null;
  const p = PROVIDERS[m.provider];
  return { ...p, darken: m.provider !== 'carto-dark' };
}

export function drawGps(ctx: Ctx, look: Look, d: HudData) {
  const { w, h } = DESIGN.gps, g = buildGps(d.gps, d.tel, d.units);
  plate(ctx, 0, 0, w, h, look);
  label(ctx, 'GPS', 22, 32, look);
  const fixText = g.fix ? `FIX${g.sats ? ' · ' + g.sats.text + ' SATS' : ''}` : g.pos ? 'FIX LOST' : 'NO FIX';
  text(ctx, fixText, 538, 32, 14, look, { align: 'right', color: g.fix ? look.accent : g.pos ? '#ffb347' : look.muted, stroke: false });

  const mx = 14, my = 44, mw = w - 28, mh = 238;
  ctx.save();
  ctx.translate(mx, my);
  ctx.beginPath(); ctx.rect(0, 0, mw, mh); ctx.clip();
  ctx.fillStyle = 'rgba(0,0,0,0.35)'; ctx.fillRect(0, 0, mw, mh);

  const prov = resolveProvider(d.hud), points = d.track;
  const view = mapView(points, g.pos, g.home, d.hud.map, mw, mh, prov?.maxZoom ?? 17);
  let tilesShown = false, offline = false;
  if (view && prov) {
    d.tiles.beginFrame();
    const stats = drawTiles(ctx, d.tiles, view.center, view.zoom, mw, mh, { template: prov.url, subdomains: prov.subdomains, attribution: prov.attribution, darken: prov.darken }, look, d.now);
    tilesShown = stats.ok > 0;
    offline = stats.ok === 0 && stats.loading === 0 && stats.failed > 0;
  }
  if (!tilesShown) mapGrid(ctx, mw, mh, look);

  if (!view) {
    text(ctx, 'WAITING FOR GPS…', mw / 2, mh / 2 + 6, 20, look, { align: 'center', color: look.muted, stroke: false });
  } else {
    const c = project(view.center, view.zoom), at = (p: LatLon) => { const q = project(p, view.zoom); return { x: mw / 2 + q.x - c.x, y: mh / 2 + q.y - c.y }; };
    if (points.length > 1) {
      ctx.save(); ctx.lineWidth = 3; ctx.lineJoin = 'round'; ctx.strokeStyle = look.accent;
      if (look.glow > 0) { ctx.shadowColor = look.accent; ctx.shadowBlur = look.glow * 0.7; }
      ctx.beginPath();
      points.forEach((p, i) => { const q = at(p); if (i) ctx.lineTo(q.x, q.y); else ctx.moveTo(q.x, q.y); });
      ctx.stroke(); ctx.restore();
    }
    if (g.home) { // home: a ring with an H
      const q = at(g.home);
      ctx.save(); ctx.strokeStyle = look.hot; ctx.lineWidth = 2.5; ctx.fillStyle = 'rgba(0,0,0,0.55)';
      ctx.beginPath(); ctx.arc(q.x, q.y, 11, 0, Math.PI * 2); ctx.fill(); ctx.stroke(); ctx.restore();
      text(ctx, 'H', q.x, q.y + 5, 14, look, { align: 'center', color: look.hot, stroke: false });
    }
    if (g.pos) { // the quad: an arrow along the heading (or the direction of travel)
      const q = at(g.pos), prev = points.length > 1 ? at(points[points.length - 2]) : null;
      const heading = g.heading?.value != null ? (g.heading.value * Math.PI) / 180 : prev ? Math.atan2(q.x - prev.x, -(q.y - prev.y)) : 0;
      const color = g.fix ? look.accent : '#ffb347';
      ctx.save(); ctx.translate(q.x, q.y); ctx.rotate(heading);
      ctx.fillStyle = color; ctx.strokeStyle = '#000'; ctx.lineWidth = 2;
      if (look.glow > 0) { ctx.shadowColor = color; ctx.shadowBlur = look.glow; }
      ctx.beginPath(); ctx.moveTo(0, -13); ctx.lineTo(9, 10); ctx.lineTo(0, 5); ctx.lineTo(-9, 10); ctx.closePath(); ctx.stroke(); ctx.fill();
      ctx.restore();
    }
    // scale bar, bottom left
    const mpp = (156543.03392 * Math.cos((view.center.lat * Math.PI) / 180)) / 2 ** view.zoom, target = 90 * mpp;
    const metres = NICE.find((n) => n >= target * 0.5) ?? NICE[NICE.length - 1], len = metres / mpp;
    if (len > 20 && len < mw * 0.6) {
      ctx.save(); ctx.strokeStyle = look.text; ctx.lineWidth = 2; ctx.fillStyle = 'rgba(0,0,0,0.5)';
      ctx.fillRect(8, mh - 30, len + 14, 22);
      ctx.beginPath(); ctx.moveTo(14, mh - 14); ctx.lineTo(14 + len, mh - 14); ctx.moveTo(14, mh - 19); ctx.lineTo(14, mh - 14); ctx.moveTo(14 + len, mh - 19); ctx.lineTo(14 + len, mh - 14); ctx.stroke();
      ctx.restore();
      text(ctx, metres >= 1000 ? `${metres / 1000} km` : `${metres} m`, 14, mh - 21, 12, look, { stroke: false });
    }
    if (offline) text(ctx, 'MAP OFFLINE · TRACK ONLY', 10, 20, 12, look, { color: '#ffb347', stroke: false });
  }
  ctx.restore();
  ctx.save(); ctx.strokeStyle = look.ring; ctx.globalAlpha = 0.5; ctx.lineWidth = 1.5; ctx.strokeRect(mx, my, mw, mh); ctx.restore();

  // readouts under the map
  const col = (i: number) => 22 + i * 106;
  label(ctx, 'HOME', col(0), 312, look, 'left', 13);
  if (g.distance && g.homeDir !== null) {
    ctx.save(); ctx.translate(col(0) + 12, 342); ctx.rotate((g.homeDir * Math.PI) / 180); ctx.fillStyle = look.hot;
    ctx.beginPath(); ctx.moveTo(0, -12); ctx.lineTo(8, 8); ctx.lineTo(0, 3); ctx.lineTo(-8, 8); ctx.closePath(); ctx.fill(); ctx.restore();
    value(ctx, g.distance.text, g.distance.unit, col(0) + 28, 354, 28, look.text, look);
  } else text(ctx, '—', col(0), 354, 28, look, { color: look.muted });
  const cells: [string, Badge | null][] = [['SPEED', g.speed], ['ALT', g.alt], ['HDG', g.heading], ['CLIMB', g.climb]];
  cells.forEach(([lab, b], i) => {
    label(ctx, lab, col(i + 1) + 8, 312, look, 'left', 13);
    if (b) value(ctx, b.text, b.unit, col(i + 1) + 8, 354, 28, b.level === 'warn' || b.level === 'crit' ? look.levelColor(b.level) : look.text, look);
    else text(ctx, '—', col(i + 1) + 8, 354, 28, look, { color: look.muted });
  });
  if (g.pos) text(ctx, `${g.pos.lat.toFixed(5)}  ${g.pos.lon.toFixed(5)}`, 22, 404, 14, look, { color: look.muted, stroke: false });
}

// ---------------------------------------------------------------- Status
const RADIO_TEXT: Record<RadioState, [string, Level]> = {
  live: ['RADIO LIVE', 'ok'], demo: ['DEMO DATA', 'warn'], paused: ['DATA PAUSED', 'warn'], disconnected: ['RADIO OFF', 'crit'], offline: ['BRIDGE OFFLINE', 'crit'],
};

export function drawStatus(ctx: Ctx, look: Look, d: HudData) {
  const { w, h } = DESIGN.status;
  plate(ctx, 0, 0, w, h, look);
  const armed = d.armed === true, known = d.armed !== null;
  const armText = !d.armSwitch ? 'NO ARM SWITCH' : !known ? 'NO DATA' : armed ? 'ARMED' : 'DISARMED';
  // ARM badge
  ctx.save();
  const pulseA = armed ? 0.75 + 0.25 * Math.sin(look.t * 6) : 1, c = armed ? '#ff5a4d' : known ? look.ok : look.muted;
  ctx.globalAlpha = pulseA; ctx.fillStyle = armed ? 'rgba(255,90,77,0.18)' : 'rgba(255,255,255,0.06)'; ctx.strokeStyle = c; ctx.lineWidth = 2.5;
  if (look.glow > 0 && armed) { ctx.shadowColor = c; ctx.shadowBlur = look.glow; }
  ctx.beginPath(); ctx.roundRect(18, 22, 158, 50, 10); ctx.fill(); ctx.stroke(); ctx.restore();
  text(ctx, armText, 97, 55, known ? 24 : 16, look, { align: 'center', color: c, glow: armed });
  // timer
  label(ctx, 'FLIGHT TIME', 196, 34, look, 'left', 13);
  text(ctx, formatClock(d.flightSeconds), 196, 76, 44, look, { color: armed ? look.text : look.muted, glow: armed });
  // throttle
  label(ctx, 'THROTTLE', 372, 34, look, 'left', 13);
  const thr = d.throttle;
  text(ctx, thr === null ? '—' : `${Math.round(thr * 100)}%`, 540, 34, 18, look, { align: 'right' });
  bar(ctx, 372, 42, 168, 12, thr, look.accent, look);
  // crash flip + radio state
  const [rt, rl] = RADIO_TEXT[d.radio];
  text(ctx, rt, 372, 94, 13, look, { color: look.levelColor(rl), stroke: false });
  if (d.flip) {
    ctx.save(); ctx.globalAlpha = 0.7 + 0.3 * Math.sin(look.t * 10); ctx.fillStyle = '#ff3b3b';
    ctx.beginPath(); ctx.roundRect(446, 76, 94, 24, 6); ctx.fill(); ctx.restore();
    text(ctx, 'CRASH FLIP', 493, 93, 13, look, { align: 'center', color: '#fff', stroke: false, weight: 'bold' });
  }
}
