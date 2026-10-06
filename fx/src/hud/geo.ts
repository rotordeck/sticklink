// Geography and slippy-map maths (Web Mercator, 256 px tiles), plus the tile providers. Pure: no DOM.

const R = 6371008.8;
const rad = (d: number) => (d * Math.PI) / 180;
const deg = (r: number) => (r * 180) / Math.PI;
export const MAX_LAT = 85.0511287798;

export interface LatLon { lat: number; lon: number }

/** Great-circle distance in metres. */
export function haversine(a: LatLon, b: LatLon): number {
  const p1 = rad(a.lat), p2 = rad(b.lat);
  const h = Math.sin((p2 - p1) / 2) ** 2 + Math.cos(p1) * Math.cos(p2) * Math.sin(rad(b.lon - a.lon) / 2) ** 2;
  return 2 * R * Math.asin(Math.min(1, Math.sqrt(h)));
}

/** Initial compass bearing from a to b, 0..360 (0 = north, 90 = east). */
export function bearing(a: LatLon, b: LatLon): number {
  const p1 = rad(a.lat), p2 = rad(b.lat), dl = rad(b.lon - a.lon);
  const y = Math.sin(dl) * Math.cos(p2);
  const x = Math.cos(p1) * Math.sin(p2) - Math.sin(p1) * Math.cos(p2) * Math.cos(dl);
  return (deg(Math.atan2(y, x)) + 360) % 360;
}

/** Pixels in the whole world at a zoom level. */
export const worldSize = (zoom: number) => 256 * 2 ** zoom;

/** Position in world pixels (origin top-left of the map, y down). */
export function project(p: LatLon, zoom: number): { x: number; y: number } {
  const lat = Math.max(-MAX_LAT, Math.min(MAX_LAT, p.lat)), size = worldSize(zoom);
  const s = Math.sin(rad(lat));
  return { x: ((p.lon + 180) / 360) * size, y: (0.5 - Math.log((1 + s) / (1 - s)) / (4 * Math.PI)) * size };
}

export function unproject(x: number, y: number, zoom: number): LatLon {
  const size = worldSize(zoom);
  return { lon: (x / size) * 360 - 180, lat: deg(Math.atan(Math.sinh(Math.PI * (1 - (2 * y) / size)))) };
}

/** Largest integer zoom at which all points fit in the given box (with padding); clamped to [min, max]. */
export function fitZoom(points: LatLon[], width: number, height: number, padding = 24, min = 1, max = 18): number {
  if (points.length < 2) return max;
  for (let z = max; z >= min; z--) {
    const xs = points.map((p) => project(p, z).x), ys = points.map((p) => project(p, z).y);
    if (Math.max(...xs) - Math.min(...xs) <= width - 2 * padding && Math.max(...ys) - Math.min(...ys) <= height - 2 * padding) return z;
  }
  return min;
}

export function boundsCenter(points: LatLon[]): LatLon {
  const lats = points.map((p) => p.lat), lons = points.map((p) => p.lon);
  return { lat: (Math.min(...lats) + Math.max(...lats)) / 2, lon: (Math.min(...lons) + Math.max(...lons)) / 2 };
}

export interface TileRef { z: number; x: number; y: number; px: number; py: number }

/** The tiles that intersect a view (and only those: no prefetch ring) with the view centred on `center`. */
export function visibleTiles(center: LatLon, zoom: number, width: number, height: number): TileRef[] {
  const c = project(center, zoom), n = 2 ** zoom, left = c.x - width / 2, top = c.y - height / 2;
  const x0 = Math.floor(left / 256), x1 = Math.floor((left + width) / 256), y0 = Math.floor(top / 256), y1 = Math.floor((top + height) / 256);
  const out: TileRef[] = [];
  for (let ty = y0; ty <= y1; ty++) {
    if (ty < 0 || ty >= n) continue;
    for (let tx = x0; tx <= x1; tx++) out.push({ z: zoom, x: ((tx % n) + n) % n, y: ty, px: tx * 256 - left, py: ty * 256 - top });
  }
  return out;
}

export interface Provider { url: string; subdomains?: string[]; attribution: string; maxZoom: number }

export const PROVIDERS: Record<'osm' | 'carto-dark' | 'carto-light', Provider> = {
  osm: { url: 'https://tile.openstreetmap.org/{z}/{x}/{y}.png', attribution: '© OpenStreetMap contributors', maxZoom: 19 },
  'carto-dark': { url: 'https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png', subdomains: ['a', 'b', 'c', 'd'], attribution: '© OpenStreetMap contributors © CARTO', maxZoom: 20 },
  'carto-light': { url: 'https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}.png', subdomains: ['a', 'b', 'c', 'd'], attribution: '© OpenStreetMap contributors © CARTO', maxZoom: 20 },
};

export function tileUrl(template: string, t: { z: number; x: number; y: number }, subdomains?: string[]): string {
  const s = subdomains?.length ? subdomains[(t.x + t.y) % subdomains.length] : '';
  return template.replace('{s}', s).replace('{z}', String(t.z)).replace('{x}', String(t.x)).replace('{y}', String(t.y));
}

/** Compact distance text: metres below 1 km, then km (or ft below 0.1 mi, then miles when imperial). */
export function formatDistance(metres: number, imperial: boolean): { text: string; unit: string } {
  if (imperial) {
    const ft = metres * 3.28084;
    return ft < 528 ? { text: String(Math.round(ft)), unit: 'ft' } : { text: (metres / 1609.344).toFixed(2), unit: 'mi' };
  }
  return metres < 1000 ? { text: String(Math.round(metres)), unit: 'm' } : { text: (metres / 1000).toFixed(2), unit: 'km' };
}

/** Which part of the world the map shows: the whole track (zoom 'auto'), or a fixed zoom following the quad or centred on home. */
export function mapView(points: LatLon[], pos: LatLon | null, home: LatLon | null, cfg: { zoom: 'auto' | number; follow: boolean },
  width: number, height: number, maxZoom: number): { center: LatLon; zoom: number } | null {
  const all = [...points, ...(pos ? [pos] : []), ...(home ? [home] : [])];
  if (!all.length) return null;
  const top = Math.min(17, maxZoom);
  if (cfg.zoom === 'auto') {
    const step = Math.max(1, Math.floor(all.length / 600)); // plenty of points for a bounding box
    const sample = all.filter((_, i) => i % step === 0 || i === all.length - 1);
    return { zoom: fitZoom(sample, width, height, 44, 1, top), center: boundsCenter(sample) };
  }
  return { zoom: Math.min(cfg.zoom, maxZoom), center: cfg.follow && pos ? pos : home ?? boundsCenter(all) };
}
