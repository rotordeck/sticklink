import { test } from 'node:test';
import assert from 'node:assert/strict';
import { DESIGN, layoutHud, layoutSingle, type Block, type Placed } from '../src/hud/layout.ts';
import { mapView, fitZoom, project } from '../src/hud/geo.ts';

const ALL: Block[] = ['link', 'battery', 'gps', 'status'];
const overlap = (a: Placed, b: Placed) => a.x < b.x + b.w - 0.01 && b.x < a.x + a.w - 0.01 && a.y < b.y + b.h - 0.01 && b.y < a.y + a.h - 0.01;

test('every layout keeps every block inside the screen, undistorted and not overlapping, at many sizes', () => {
  const sizes: [number, number][] = [[1920, 1080], [1280, 720], [3840, 2160], [1000, 600], [800, 450], [576, 450], [450, 576], [2560, 1080]];
  for (const layout of ['corners', 'row', 'column'] as const) for (const [W, H] of sizes) {
    const placed = layoutHud(layout, ALL, W, H), list = Object.entries(placed) as [Block, Placed][];
    assert.equal(list.length, 4);
    for (const [b, p] of list) {
      assert.ok(p.x >= -0.01 && p.y >= -0.01 && p.x + p.w <= W + 0.01 && p.y + p.h <= H + 0.01, `${layout} ${W}x${H} ${b} inside: ${JSON.stringify(p)}`);
      assert.ok(Math.abs(p.w / p.h - DESIGN[b].w / DESIGN[b].h) < 1e-9, `${b} keeps its aspect ratio`);
      assert.ok(Math.abs(p.w - DESIGN[b].w * p.scale) < 1e-9);
    }
    // 'corners' needs room: only check overlaps where the screen is at least a quarter of the reference size
    if (layout !== 'corners' || W * H >= 1280 * 720) {
      for (let i = 0; i < list.length; i++) for (let j = i + 1; j < list.length; j++) {
        assert.ok(!overlap(list[i][1], list[j][1]), `${layout} ${W}x${H}: ${list[i][0]} overlaps ${list[j][0]}`);
      }
    }
  }
});

test('corners puts each block in its own corner at the reference size', () => {
  const p = layoutHud('corners', ALL, 1920, 1080);
  assert.deepEqual([p.link!.x, p.link!.y, p.link!.scale], [40, 40, 1]);
  assert.equal(p.battery!.y + p.battery!.h, 1080 - 40);
  assert.equal(p.gps!.x + p.gps!.w, 1920 - 40);
  assert.equal(p.status!.y, 40);
});

test('only the enabled blocks are placed; none enabled places nothing', () => {
  assert.deepEqual(Object.keys(layoutHud('row', ['link', 'gps'], 1920, 1080)), ['link', 'gps']);
  assert.deepEqual(layoutHud('column', [], 1920, 1080), {});
  const row = layoutHud('row', ['battery'], 1920, 1080);
  assert.ok(Math.abs(row.battery!.x + row.battery!.w / 2 - 960) < 0.01, 'a lone row block is centred horizontally');
});

test('a single block page centres the block and fills the source', () => {
  for (const [W, H] of [[1920, 1080], [576, 450], [300, 800], [4000, 300]]) for (const b of ALL) {
    const p = layoutSingle(b, W, H);
    assert.ok(Math.abs(p.x + p.w / 2 - W / 2) < 0.01 && Math.abs(p.y + p.h / 2 - H / 2) < 0.01, `${b} centred in ${W}x${H}`);
    assert.ok(p.w <= W * 0.94 + 0.01 && p.h <= H * 0.94 + 0.01);
    assert.ok(Math.abs(p.w - W * 0.94) < 0.01 || Math.abs(p.h - H * 0.94) < 0.01, 'touches the margin on its limiting side');
  }
});

test('map view: auto zoom fits the track, fixed zoom follows the quad or centres on home', () => {
  const home = { lat: 51.0543, lon: 3.7174 }, pos = { lat: 51.0563, lon: 3.7194 };
  const track = [home, { lat: 51.0550, lon: 3.7180 }, pos];
  const auto = mapView(track, pos, home, { zoom: 'auto', follow: true }, 560, 420, 19)!;
  const xy = [home, pos].map((p) => project(p, auto.zoom));
  assert.ok(Math.abs(xy[0].x - xy[1].x) <= 560 - 88 && Math.abs(xy[0].y - xy[1].y) <= 420 - 88, 'auto zoom fits with padding');
  assert.ok(auto.zoom >= 15 && auto.zoom <= 17);
  const followed = mapView(track, pos, home, { zoom: 16, follow: true }, 560, 420, 19)!;
  assert.deepEqual([followed.zoom, followed.center], [16, pos]);
  assert.deepEqual(mapView(track, pos, home, { zoom: 16, follow: false }, 560, 420, 19)!.center, home);
  assert.equal(mapView(track, pos, home, { zoom: 19, follow: true }, 560, 420, 15)!.zoom, 15, 'never beyond what the provider serves');
  assert.equal(mapView([], null, null, { zoom: 'auto', follow: true }, 560, 420, 19), null, 'nothing to show yet');
  assert.equal(mapView([], pos, null, { zoom: 'auto', follow: true }, 560, 420, 19)!.zoom, 17, 'a single point: street level');
  const many = Array.from({ length: 5000 }, (_, i) => ({ lat: 51 + i * 1e-5, lon: 3.7 }));
  assert.ok(mapView(many, many.at(-1)!, many[0], { zoom: 'auto', follow: true }, 560, 420, 19)!.zoom >= fitZoom([many[0], many.at(-1)!], 560, 420, 44, 1, 17) - 0, 'a long track is sampled, still fits');
});
