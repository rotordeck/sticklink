import { test } from 'node:test';
import assert from 'node:assert/strict';
import { bearing, fitZoom, formatDistance, haversine, project, tileUrl, unproject, visibleTiles, worldSize, PROVIDERS } from '../src/hud/geo.ts';

const near = (a: number, b: number, tol: number, msg = '') => assert.ok(Math.abs(a - b) <= tol, `${msg} ${a} vs ${b} (tolerance ${tol})`);

test('distance and bearing match independently verified values (same as the Python side)', () => {
  const brussels = { lat: 50.8503, lon: 4.3517 }, paris = { lat: 48.8566, lon: 2.3522 };
  near(haversine(brussels, paris) / 1000, 263.98, 0.05, 'Brussels-Paris km');
  near(bearing(brussels, paris), 213.656, 0.01, 'bearing');
  near(haversine({ lat: 0, lon: 0 }, { lat: 0, lon: 1 }) / 1000, 111.19, 0.01);
  for (const [to, expect] of [[{ lat: 1, lon: 0 }, 0], [{ lat: 0, lon: 1 }, 90], [{ lat: -1, lon: 0 }, 180], [{ lat: 0, lon: -1 }, 270]] as const) {
    near(bearing({ lat: 0, lon: 0 }, to), expect, 0.01, `bearing to ${JSON.stringify(to)}`);
  }
  assert.equal(haversine(brussels, brussels), 0);
});

test('Web Mercator: the world is a 256*2^z square and projection round-trips', () => {
  assert.equal(worldSize(0), 256);
  const origin = project({ lat: 0, lon: 0 }, 0);
  near(origin.x, 128, 1e-9); near(origin.y, 128, 1e-9);
  near(project({ lat: 0, lon: -180 }, 3).x, 0, 1e-9);
  near(project({ lat: 0, lon: 180 }, 3).x, worldSize(3), 1e-9);
  for (const z of [1, 8, 15, 19]) for (const p of [{ lat: 51.0543, lon: 3.7174 }, { lat: -33.86, lon: 151.21 }, { lat: 70, lon: -150 }]) {
    const xy = project(p, z), back = unproject(xy.x, xy.y, z);
    near(back.lat, p.lat, 1e-7, `lat z${z}`); near(back.lon, p.lon, 1e-7, `lon z${z}`);
  }
  assert.ok(project({ lat: 60, lon: 0 }, 5).y < project({ lat: 10, lon: 0 }, 5).y, 'north is up (smaller y)');
});

test('the tile covering a point has the number an independent formula gives', () => {
  const p = { lat: 51.5, lon: -0.12 }, z = 10, n = 2 ** z;
  const x = Math.floor(((p.lon + 180) / 360) * n), y = Math.floor(((1 - Math.asinh(Math.tan((p.lat * Math.PI) / 180)) / Math.PI) / 2) * n);
  assert.deepEqual([x, y], [511, 340], 'London at zoom 10 is the well-known tile 511/340');
  const tiles = visibleTiles(p, z, 100, 100);
  assert.ok(tiles.some((t) => t.x === x && t.y === y), 'visibleTiles includes it');
});

test('visibleTiles covers the view exactly: every tile touches it, nothing is missing, nothing outside the world', () => {
  for (const [lat, lon, z, w, h] of [[51.05, 3.72, 15, 576, 450], [0, 0, 1, 300, 200], [-80, 10, 6, 800, 600], [10, 179.99, 5, 500, 500], [85, -179.99, 4, 640, 360]] as const) {
    const tiles = visibleTiles({ lat, lon }, z, w, h), n = 2 ** z;
    for (const t of tiles) {
      assert.ok(t.px < w && t.px + 256 > 0 && t.py < h && t.py + 256 > 0, `tile ${t.z}/${t.x}/${t.y} touches the view`);
      assert.ok(t.x >= 0 && t.x < n && t.y >= 0 && t.y < n, 'inside the world (x wraps around the antimeridian)');
    }
    // every pixel row/column of the view is covered by some tile
    for (const [sx, sy] of [[0, 0], [w - 1, 0], [0, h - 1], [w - 1, h - 1], [w >> 1, h >> 1]]) {
      assert.ok(tiles.some((t) => sx >= t.px && sx < t.px + 256 && sy >= t.py && sy < t.py + 256) || lat > 84 || lat < -84, `pixel ${sx},${sy} covered`);
    }
    assert.ok(tiles.length <= (Math.ceil(w / 256) + 1) * (Math.ceil(h / 256) + 1), 'no prefetch ring beyond the view');
  }
});

test('fitZoom picks the largest zoom at which the points fit, and one more would not', () => {
  const home = { lat: 51.0543, lon: 3.7174 };
  const near100m = [home, { lat: home.lat + 0.0009, lon: home.lon }];
  const far100km = [home, { lat: home.lat + 0.9, lon: home.lon + 0.9 }];
  const span = (pts: typeof near100m, z: number) => {
    const xy = pts.map((p) => project(p, z));
    return [Math.max(...xy.map((p) => p.x)) - Math.min(...xy.map((p) => p.x)), Math.max(...xy.map((p) => p.y)) - Math.min(...xy.map((p) => p.y))];
  };
  for (const pts of [near100m, far100km]) {
    const z = fitZoom(pts, 576, 450, 24), [sx, sy] = span(pts, z);
    assert.ok(sx <= 576 - 48 && sy <= 450 - 48, `fits at ${z}`);
    if (z < 18) { const [ex, ey] = span(pts, z + 1); assert.ok(ex > 576 - 48 || ey > 450 - 48, `would not fit at ${z + 1}`); }
  }
  assert.ok(fitZoom(near100m, 576, 450) > fitZoom(far100km, 576, 450) + 6, 'a bigger area needs a much lower zoom');
  assert.equal(fitZoom([home], 576, 450), 18, 'a single point uses the maximum zoom');
  assert.equal(fitZoom([{ lat: -60, lon: -170 }, { lat: 60, lon: 170 }], 100, 100, 24, 1, 18), 1, 'never below the minimum');
});

test('tile URLs and distance text', () => {
  assert.equal(tileUrl(PROVIDERS.osm.url, { z: 10, x: 511, y: 340 }), 'https://tile.openstreetmap.org/10/511/340.png');
  const carto = tileUrl(PROVIDERS['carto-dark'].url, { z: 3, x: 1, y: 2 }, PROVIDERS['carto-dark'].subdomains);
  assert.equal(carto, 'https://d.basemaps.cartocdn.com/dark_all/3/1/2.png');
  assert.equal(tileUrl('http://127.0.0.1:9/{z}/{x}/{y}.png', { z: 1, x: 0, y: 1 }), 'http://127.0.0.1:9/1/0/1.png');
  assert.deepEqual(formatDistance(123.4, false), { text: '123', unit: 'm' });
  assert.deepEqual(formatDistance(1234, false), { text: '1.23', unit: 'km' });
  assert.deepEqual(formatDistance(100, true), { text: '328', unit: 'ft' });
  assert.deepEqual(formatDistance(1000, true), { text: '0.62', unit: 'mi' });
  assert.ok(PROVIDERS.osm.attribution.includes('OpenStreetMap contributors'), 'OSM requires visible attribution');
  assert.ok(PROVIDERS['carto-dark'].attribution.includes('CARTO'));
});
