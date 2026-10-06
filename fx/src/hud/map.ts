// Slippy-map tiles on a canvas, written to the OpenStreetMap tile usage policy:
//  - only tiles that are visible are requested (no prefetching / bulk loading), a few at a time;
//  - tiles come through the browser's own image loading, so its HTTP cache is honoured and the normal Referer is sent
//    (no referrerPolicy is set and no cache-busting is added);
//  - attribution is always drawn on the map when tiles are shown.
import { visibleTiles, tileUrl, type LatLon } from './geo.ts';
import type { Ctx, Look } from './look.ts';

type State = 'loading' | 'ok' | 'error';
interface Entry { img: HTMLImageElement; state: State; used: number; since: number }

const MAX_CONCURRENT = 4, MAX_ENTRIES = 80, TIMEOUT_MS = 8000, RETRY_MS = 30000;

export interface MapStats { wanted: number; ok: number; failed: number; loading: number }

export class TileMap {
  private cache = new Map<string, Entry>();
  private active = 0;
  private queue: string[] = [];
  /** Test hook: how images are created (the page uses a real Image). */
  private make: () => HTMLImageElement;
  constructor(make: () => HTMLImageElement = () => new Image()) { this.make = make; }

  /** Call once per frame before asking for tiles: only what is asked for in a frame is ever loaded. */
  beginFrame() { this.queue.length = 0; }

  private start(url: string, now: number) {
    const entry: Entry = { img: this.make(), state: 'loading', used: now, since: now };
    this.cache.set(url, entry); this.active++;
    const done = (state: State) => { if (entry.state !== 'loading') return; entry.state = state; entry.since = performance.now(); this.active--; this.pump(); };
    entry.img.onload = () => done('ok');
    entry.img.onerror = () => done('error');
    entry.img.decoding = 'async';
    entry.img.src = url;
    const timer: any = setTimeout(() => { if (entry.state === "loading") { entry.img.src = ""; done("error"); } }, TIMEOUT_MS);
    timer?.unref?.(); // never keep a Node test process waiting
  }

  private pump() {
    const now = performance.now();
    while (this.active < MAX_CONCURRENT && this.queue.length) {
      const url = this.queue.shift()!;
      if (!this.cache.has(url)) this.start(url, now);
    }
  }

  /** The entry for a tile, starting (or queueing) its load if it has not been asked for yet. */
  get(url: string, now: number): Entry | undefined {
    const hit = this.cache.get(url);
    if (hit) {
      hit.used = now;
      if (hit.state === 'error' && now - hit.since > RETRY_MS) this.cache.delete(url); // try again later, not every frame
      else return hit;
    }
    if (this.active < MAX_CONCURRENT) this.start(url, now);
    else if (!this.queue.includes(url)) this.queue.push(url);
    this.evict();
    return this.cache.get(url);
  }

  private evict() {
    if (this.cache.size <= MAX_ENTRIES) return;
    const old = [...this.cache.entries()].filter(([, e]) => e.state !== 'loading').sort((a, b) => a[1].used - b[1].used);
    for (const [url] of old.slice(0, this.cache.size - MAX_ENTRIES)) this.cache.delete(url);
  }
}

export interface MapOptions {
  template: string; subdomains?: string[]; attribution: string;
  /** Light tile sets are inverted and tinted to sit in a dark HUD; dark ones are used as they are. */
  darken: boolean;
}

/** Draw the tiles for a view into (0, 0, w, h) of the current transform. Returns what happened, for the caller's fallback. */
export function drawTiles(ctx: Ctx, tm: TileMap, center: LatLon, zoom: number, w: number, h: number, o: MapOptions, look: Look, now: number): MapStats {
  const tiles = visibleTiles(center, zoom, w, h), stats: MapStats = { wanted: tiles.length, ok: 0, failed: 0, loading: 0 };
  ctx.save();
  ctx.beginPath(); ctx.rect(0, 0, w, h); ctx.clip();
  if (o.darken) ctx.filter = 'invert(1) grayscale(1) brightness(0.7) contrast(1.15)';
  for (const t of tiles) {
    const e = tm.get(tileUrl(o.template, t, o.subdomains), now);
    if (e?.state === 'ok') { ctx.drawImage(e.img, t.px, t.py, 256, 256); stats.ok++; }
    else if (e?.state === 'error') stats.failed++;
    else stats.loading++;
  }
  ctx.filter = 'none';
  if (stats.ok && o.darken) { // tint towards the style's accent colour
    ctx.globalCompositeOperation = 'color'; ctx.globalAlpha = 0.45; ctx.fillStyle = look.accent; ctx.fillRect(0, 0, w, h);
    ctx.globalCompositeOperation = 'source-over'; ctx.globalAlpha = 1;
  }
  if (stats.ok) { // attribution, always visible, bottom right
    const px = 11;
    ctx.font = look.font(px); ctx.textBaseline = 'alphabetic';
    const tw = ctx.measureText(o.attribution).width + 12;
    ctx.fillStyle = 'rgba(0,0,0,0.62)'; ctx.fillRect(w - tw, h - px - 8, tw, px + 8);
    ctx.fillStyle = 'rgba(255,255,255,0.92)'; ctx.textAlign = 'right'; ctx.fillText(o.attribution, w - 6, h - 6);
  }
  ctx.restore();
  return stats;
}
