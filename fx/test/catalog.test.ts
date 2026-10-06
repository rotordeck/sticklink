import { test } from 'node:test';
import assert from 'node:assert/strict';
import { badge, buildBattery, buildGps, buildLink, cellLevel, formatClock, levelOf, others, raceTime, type Telemetry } from '../src/hud/catalog.ts';
import { History } from '../src/hud/history.ts';
import { DEFAULT_HUD, cleanHud } from '../src/config.ts';

const S = (value: number, current = true) => ({ value, current, fresh: current, age_ms: 10 });
const kmh = { speed: 'kmh', alt: 'm' } as const;
const imperial = { speed: 'mph', alt: 'ft' } as const;

test('thresholds are higher-is-better and inclusive at the boundary', () => {
  assert.equal(levelOf(80, { ok: 80, warn: 60 }), 'ok');
  assert.equal(levelOf(79.9, { ok: 80, warn: 60 }), 'warn');
  assert.equal(levelOf(60, { ok: 80, warn: 60 }), 'warn');
  assert.equal(levelOf(59.9, { ok: 80, warn: 60 }), 'crit');
  assert.equal(levelOf(5, {}), 'ok', 'no thresholds means informational');
  assert.equal(cellLevel(3.5), 'ok'); assert.equal(cellLevel(3.49), 'warn'); assert.equal(cellLevel(3.3), 'warn'); assert.equal(cellLevel(3.29), 'crit');
});

test('badges: text, unit, bar fraction and level per sensor; stale sensors go dark', () => {
  const tel: Telemetry = { RQly: S(85), RSNR: S(-3), '1RSS': S(-95), TPWR: S(250), RFMD: S(7), Gizmo: S(1.234) };
  const q = badge('RQly', tel, kmh)!;
  assert.deepEqual([q.label, q.text, q.unit, q.level, q.frac], ['LINK', '85', '%', 'ok', 0.85]);
  assert.equal(badge('RQly', { RQly: S(70) }, kmh)!.level, 'warn');
  assert.equal(badge('RQly', { RQly: S(40) }, kmh)!.level, 'crit');
  const snr = badge('RSNR', tel, kmh)!;
  assert.deepEqual([snr.text, snr.level], ['-3', 'crit']);
  assert.equal(snr.frac, 0.425, '(-3 + 20) / 40');
  assert.equal(badge('1RSS', tel, kmh)!.level, 'warn', '-95 dBm is between -85 and -100');
  assert.equal(badge('TPWR', tel, kmh)!.frac, null, 'no bar for informational values');
  const stale = badge('RQly', { RQly: S(99, false) }, kmh)!;
  assert.deepEqual([stale.text, stale.level, stale.value, stale.frac], ['—', 'off', null, null]);
  const generic = badge('Gizmo', tel, kmh)!;
  assert.deepEqual([generic.label, generic.text, generic.level], ['GIZMO', '1.2', 'ok'], 'unknown sensors still get a badge');
  assert.equal(badge('Nope', tel, kmh), null);
});

test('unit conversions: speed, altitude and attitude radians', () => {
  const tel: Telemetry = { GSpd: S(100), Alt: S(100), Ptch: S(Math.PI / 2), VSpd: S(2.5) };
  assert.deepEqual([badge('GSpd', tel, kmh)!.text, badge('GSpd', tel, kmh)!.unit], ['100', 'km/h']);
  assert.deepEqual([badge('GSpd', tel, imperial)!.text, badge('GSpd', tel, imperial)!.unit], ['62', 'mph']);
  assert.deepEqual([badge('Alt', tel, imperial)!.text, badge('Alt', tel, imperial)!.unit], ['328', 'ft']);
  assert.equal(badge('Ptch', tel, kmh)!.text, '90');
  assert.equal(badge('VSpd', tel, imperial)!.text, '2.5', 'climb rate is not converted');
});

test('link model groups the sensors that were received', () => {
  const tel: Telemetry = { RQly: S(99), RSNR: S(10), '1RSS': S(-60), '2RSS': S(-64), TPWR: S(250), RFMD: S(7), TQly: S(100) };
  const link = buildLink(tel, kmh);
  assert.equal(link.present, true);
  assert.equal(link.quality!.text, '99');
  assert.deepEqual(link.signal.map((b) => b.id), ['RSNR', '1RSS', '2RSS']);
  assert.deepEqual(link.radio.map((b) => b.id), ['TPWR', 'RFMD']);
  assert.deepEqual(link.uplink.map((b) => b.id), ['TQly']);
  const none = buildLink({}, kmh);
  assert.deepEqual([none.present, none.quality, none.signal.length], [false, null, 0]);
});

test('battery: per-cell voltage and level from the cell count, power, fraction', () => {
  const tel = (v: number): Telemetry => ({ RxBt: S(v), Curr: S(20), Capa: S(500), 'Bat%': S(64) });
  const four = buildBattery(tel(16.4), 4, kmh);
  assert.deepEqual([four.volts, four.perCell, four.level], [16.4, 4.1, 'ok']);
  assert.equal(four.watts, 328);
  assert.ok(Math.abs(four.frac! - (4.1 - 3.3) / 0.9) < 1e-9);
  assert.equal(buildBattery(tel(14.0), 4, kmh).level, 'ok', '3.50 V per cell');
  assert.equal(buildBattery(tel(13.8), 4, kmh).level, 'warn', '3.45 V per cell');
  assert.equal(buildBattery(tel(12.8), 4, kmh).level, 'crit', '3.20 V per cell');
  assert.equal(buildBattery(tel(16.4), 6, kmh).level, 'crit', 'the cell count matters: the same pack as 6S is flat');
  assert.deepEqual([four.current!.text, four.used!.text, four.percent!.text], ['20.0', '500', '64']);
  const gone = buildBattery({ RxBt: S(16.4, false) }, 4, kmh);
  assert.deepEqual([gone.volts, gone.level, gone.watts], [null, 'off', null]);
  assert.equal(buildBattery({ RxBt: S(0) }, 4, kmh).volts, null, 'a 0 V reading is "no data", not a flat pack');
  assert.equal(buildBattery({}, 4, kmh).present, false);
});

test('gps model: bridge figures win, home direction is the reverse bearing, sensors fill the rest', () => {
  const gps = { fix: true, lat: 51.001, lon: 3.7, age_ms: 100, home: { lat: 51.0, lon: 3.7 }, distance_m: 111.2, bearing_deg: 0 };
  const m = buildGps(gps, { Sats: S(14), GSpd: S(36), GAlt: S(40), Alt: S(35), Hdg: S(270), VSpd: S(-1) }, kmh);
  assert.deepEqual([m.present, m.fix, m.distance, m.bearing, m.homeDir], [true, true, { text: '111', unit: 'm' }, 0, 180]);
  assert.equal(m.alt!.text, '40', 'GPS altitude preferred over barometric');
  assert.deepEqual([m.sats!.level, m.speed!.text, m.heading!.text], ['ok', '36', '270']);
  const noFigures = buildGps({ ...gps, distance_m: null, bearing_deg: null }, {}, kmh);
  assert.equal(noFigures.distance!.text, '111', 'recomputed from home and position (111.2 m)');
  assert.equal(noFigures.bearing, 0);
  assert.equal(buildGps({ ...gps, home: null, distance_m: null, bearing_deg: null }, {}, kmh).distance, null);
  const empty = buildGps({ fix: false, lat: null, lon: null, age_ms: null, home: null, distance_m: null, bearing_deg: null }, {}, kmh);
  assert.deepEqual([empty.present, empty.fix, empty.pos], [false, false, null]);
  assert.equal(buildGps(null, {}, kmh).present, false);
  assert.equal(buildGps(gps, {}, imperial).distance!.unit, 'ft');
});

test('others() lists only sensors that belong to no block', () => {
  const o = others({ RQly: S(1), RxBt: S(2), Sats: S(3), Zeta: S(4), Alpha: S(5), Ptch: S(0.1) }, kmh);
  assert.deepEqual(o.map((b) => b.id), ['Alpha', 'Ptch', 'Zeta']);
});

test('clock text', () => {
  assert.equal(formatClock(0), '00:00'); assert.equal(formatClock(75.9), '01:15'); assert.equal(formatClock(3725), '1:02:05'); assert.equal(formatClock(-5), '00:00');
});

test('history samples at a fixed interval and keeps a bounded window', () => {
  const h = new History(250, 5);
  for (let t = 0; t < 2000; t += 50) h.push('v', t, t);
  assert.deepEqual(h.series('v'), [750, 1000, 1250, 1500, 1750], 'one sample per 250 ms, newest five kept');
  assert.deepEqual(h.series('missing'), []);
  h.reset(); assert.deepEqual(h.series('v'), []);
});

test('cleanHud accepts good input and keeps the base for anything invalid', () => {
  const styles = ['neon', 'hacker'];
  const good = cleanHud({ style: 'hacker', layout: 'row', cells: 6, blocks: { gps: false }, units: { speed: 'mph' },
    map: { provider: 'custom', customUrl: 'http://127.0.0.1:9000/{z}/{x}/{y}.png', attribution: 'Test', zoom: 14, follow: false } }, DEFAULT_HUD, styles);
  assert.deepEqual([good.style, good.layout, good.cells, good.blocks.gps, good.blocks.link, good.units.speed, good.units.alt], ['hacker', 'row', 6, false, true, 'mph', 'm']);
  assert.deepEqual(good.map, { provider: 'custom', customUrl: 'http://127.0.0.1:9000/{z}/{x}/{y}.png', attribution: 'Test', zoom: 14, follow: false });
  assert.equal(cleanHud({ style: null }, { ...DEFAULT_HUD, style: 'neon' }, styles).style, null);
  for (const bad of [
    { style: 'nope' }, { layout: 'diagonal' }, { map: { provider: 'bing' } }, { map: { customUrl: 'http://evil.example/{z}/{x}/{y}.png' } },
    { map: { customUrl: 'https://t.example/{z}/{x}.png' } }, { map: { customUrl: 'javascript:alert(1)//{z}{x}{y}' } },
    { map: { customUrl: 'https://t.example/{z}/{x}/{y}.png"onerror=' } }, { map: { attribution: '<b>x</b>' } }, { blocks: { gps: 'yes' } }, { units: { speed: 'knots' } },
  ]) assert.deepEqual(cleanHud(bad, DEFAULT_HUD, styles), DEFAULT_HUD, JSON.stringify(bad));
  assert.equal(cleanHud({ cells: 99 }, DEFAULT_HUD, styles).cells, 8);
  assert.equal(cleanHud({ map: { zoom: 99 } }, DEFAULT_HUD, styles).map.zoom, 19);
  assert.equal(cleanHud({ map: { zoom: 'auto' } }, { ...DEFAULT_HUD, map: { ...DEFAULT_HUD.map, zoom: 12 } }, styles).map.zoom, 'auto');
  assert.deepEqual(cleanHud('junk', DEFAULT_HUD, styles), DEFAULT_HUD);
});

test('raceTime splits seconds and tenths from the last two digits, and adds minutes from 1:00', () => {
  assert.deepEqual(raceTime(0), { main: '0.0', small: '00' });
  assert.deepEqual(raceTime(12347), { main: '12.3', small: '47' });
  assert.deepEqual(raceTime(59999), { main: '59.9', small: '99' }); // never rounds up into 60.0
  assert.deepEqual(raceTime(62050), { main: '1:02.0', small: '50' });
  assert.deepEqual(raceTime(-5), { main: '0.0', small: '00' });
});
