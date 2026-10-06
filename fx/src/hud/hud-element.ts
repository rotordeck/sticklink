// <stick-hud>: the Link / Battery / GPS HUD. One page for the combined HUD (/hud) and one per block (/hud/link, /battery, /gps).
import { DEFAULTS, clean, cleanHud, type FxConfig, type HudConfig } from '../config.ts';
import { PRESETS, presetById, STYLE_IDS as STYLES } from '../render/style.ts';
import { loadThemes } from '../themes.ts';
import { applyMapping } from '../mapping.ts';
import { PARAM, decodeConfig, permalink } from '../permalink.ts';
import { LINK_CSS, LINK_HTML, LinkRow } from '../permalink-ui.ts';
import { drawBattery, drawGps, drawLink, drawStatus, type HudData, type RadioState } from './blocks.ts';
import { layoutHud, layoutSingle, type Block } from './layout.ts';
import { brackets, makeLook, scanlines } from './look.ts';
import { haversine } from './geo.ts';
import { History } from './history.ts';
import { TileMap } from './map.ts';
// @ts-ignore plain JS module shared with the other overlays
import { StickLinkClient } from '../../../src/sticklink/web/client.js';

const FONTS = ['16px Bungee', 'italic 900 16px Orbitron', '700 16px Fredoka', '16px VT323'];
const DRAW: Record<Block, (ctx: CanvasRenderingContext2D, look: ReturnType<typeof makeLook>, d: HudData) => void> = {
  link: drawLink, battery: drawBattery, gps: drawGps, status: drawStatus,
};

/** /hud shows everything; /hud/link, /hud/battery and /hud/gps show one block. */
export function blockFromPath(path: string): Block | 'all' {
  const m = /^\/hud\/(link|battery|gps|status)\/?$/.exec(path);
  return m ? (m[1] as Block) : 'all';
}

export class StickHud extends HTMLElement {
  private cfg: FxConfig = { ...DEFAULTS };
  private canvas = document.createElement('canvas');
  private panel = document.createElement('div');
  private ctx = this.canvas.getContext('2d')!;
  private client: any;
  private block: Block | 'all' = 'all';
  private tiles = new TileMap();
  private history = new History();
  private track: { lat: number; lon: number }[] = [];
  private lastTrackFetch = 0;
  private armedAt: number | null = null; private flight = 0; private wasArmed = false;
  private editedAt = -Infinity; // when the user last changed a setting here: polled server settings must not overwrite a fresh edit
  private pinned = false; // opened from a ?cfg= link: use exactly that, never touch the server's saved settings
  private linkRow!: LinkRow;
  private formError = ''; // shown in the panel until the offending field is valid again
  private raf = 0; private ready = false; private serverJson = ''; private poll: any; private saveTimer: any;

  constructor() {
    super();
    const root = this.attachShadow({ mode: 'open' });
    root.innerHTML = `<style>
      :host{display:block;position:fixed;inset:0}canvas{display:block}
      .panel{position:fixed;inset:8px auto auto 8px;max-width:min(360px,calc(100vw - 16px));max-height:calc(100vh - 16px);overflow:auto;box-sizing:border-box;
        padding:12px 14px;border-radius:10px;background:#0b1420f2;border:1px solid #7d94ac66;color:#e6eef7;font:12px/1.4 Arial,sans-serif;z-index:10}
      .panel[hidden]{display:none}h3{margin:0 0 8px;font-size:13px;letter-spacing:1px}h4{margin:12px 0 4px;font-size:11px;letter-spacing:1px;color:#9fb2c4}
      label{display:flex;align-items:center;justify-content:space-between;gap:8px;margin:5px 0}
      select,input[type=number],input[type=text]{background:#16273a;color:inherit;border:1px solid #4a6078;border-radius:4px;padding:3px 5px;font:inherit;max-width:62%}
      input[type=text]{width:62%}.row{display:flex;gap:10px;flex-wrap:wrap}.row label{margin:2px 0;gap:4px}
      .hint{color:#9fb2c4;font-size:11px;margin-top:8px}.status{color:#50e0c1}a{color:#50e0c1}
      button{margin-top:8px;background:#16273a;color:inherit;border:1px solid #4a6078;border-radius:4px;padding:4px 10px;font:inherit;cursor:pointer}${LINK_CSS}
    </style>`;
    this.panel.className = 'panel'; this.panel.hidden = true;
    root.append(this.canvas, this.panel);
    this.panel.addEventListener('dblclick', (e) => e.stopPropagation());
  }

  async connectedCallback() {
    await loadThemes();
    this.block = blockFromPath(location.pathname);
    const link = decodeConfig(new URLSearchParams(location.search).get(PARAM));
    this.pinned = link !== null;
    if (link) this.cfg = clean(link, DEFAULTS, STYLES); // a link is applied on the defaults, independent of what is saved
    else await this.fetchConfig();
    this.buildPanel();
    this.client = new StickLinkClient(this.cfg.delay);
    this.client.start();
    await this.fetchTrack();
    window.addEventListener('resize', this.resize); this.resize();
    document.addEventListener('dblclick', this.toggle); document.addEventListener('keydown', this.onKey);
    if (!this.pinned) this.poll = setInterval(() => { if (performance.now() - this.editedAt > 2500) void this.fetchConfig().then((changed) => changed && this.syncPanel()); }, 2000);
    Promise.race([Promise.all(FONTS.map((f) => document.fonts.load(f))), new Promise((r) => setTimeout(r, 3000))]).catch(() => {}).finally(() => { this.ready = true; });
    this.raf = requestAnimationFrame(this.frame);
  }

  disconnectedCallback() {
    cancelAnimationFrame(this.raf); clearInterval(this.poll);
    window.removeEventListener('resize', this.resize); document.removeEventListener('dblclick', this.toggle); document.removeEventListener('keydown', this.onKey);
    this.client?.stop();
  }

  private resize = () => {
    const dpr = Math.max(1, window.devicePixelRatio || 1), w = window.innerWidth || 576, h = window.innerHeight || 450;
    this.canvas.width = Math.round(w * dpr); this.canvas.height = Math.round(h * dpr);
    this.canvas.style.width = `${w}px`; this.canvas.style.height = `${h}px`;
  };
  private toggle = () => { this.panel.hidden = !this.panel.hidden; if (!this.panel.hidden) this.syncPanel(); };
  private onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') this.panel.hidden = true; };

  // ------------------------------------------------------------ settings and track
  private async fetchConfig(): Promise<boolean> {
    try {
      const res = await fetch('/api/v1/settings', { cache: 'no-store' }), text = await res.text();
      if (!res.ok || text === this.serverJson) return false;
      this.serverJson = text;
      this.cfg = clean(JSON.parse(text), this.cfg, STYLES);
      return true;
    } catch { return false; }
  }

  private save() {
    clearTimeout(this.saveTimer);
    if (this.pinned) { this.panel.querySelector('.status')!.textContent = this.formError || 'Not saved on the server (opened from a link)'; return; }
    this.saveTimer = setTimeout(async () => {
      const status = this.panel.querySelector('.status')!;
      try {
        const res = await fetch('/api/v1/settings', { method: 'PATCH', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ hud: this.cfg.hud }) });
        if (res.ok) this.serverJson = JSON.stringify(await res.json());
        status.textContent = this.formError || (res.ok ? 'Saved' : 'Could not save');
      } catch { status.textContent = this.formError || 'Could not save'; }
    }, 300);
  }

  private async fetchTrack() {
    this.lastTrackFetch = performance.now();
    try {
      const body = await (await fetch('/api/v1/gps/track', { cache: 'no-store' })).json();
      this.track = body.points.map(([lat, lon]: [number, number]) => ({ lat, lon }));
    } catch { /* keep what we have */ }
  }

  private async clearTrack() {
    try { await fetch('/api/v1/gps/track', { method: 'DELETE' }); } catch { /* ignore */ }
    this.track = [];
  }

  /** Keep the local track in step with the bridge: append live fixes, refetch after a clear or a long gap. */
  private updateTrack(state: any) {
    const g = state?.gps;
    if (!g) return;
    if (g.track_points < this.track.length - 1) { this.track = []; void this.fetchTrack(); return; }
    if (Math.abs(g.track_points - this.track.length) > 3 && performance.now() - this.lastTrackFetch > 3000) { void this.fetchTrack(); return; }
    if (g.fix && g.lat !== null && g.lon !== null) {
      const last = this.track.at(-1), here = { lat: g.lat, lon: g.lon };
      if (!last || haversine(last, here) >= 2) this.track.push(here);
      if (this.track.length > 5000) this.track.shift();
    }
  }

  // ------------------------------------------------------------ drawing
  private frame = (ts: number) => {
    this.raf = requestAnimationFrame(this.frame);
    if (!this.ready) return;
    const { state, transportLive } = this.client.step();
    const mapped = applyMapping(state, this.cfg.mapping), live = transportLive && mapped.live, now = ts / 1000;
    this.updateTrack(state);
    const tel = state?.telemetry ?? {};
    if (tel.RQly?.current) this.history.push('RQly', tel.RQly.value, ts);
    if (tel.RxBt?.current && tel.RxBt.value > 0) this.history.push('RxBt', tel.RxBt.value, ts);
    // flight timer: runs while the mapped ARM switch is on, and stays on screen after disarming
    const armed = live && mapped.arm === true;
    if (armed && !this.wasArmed) { this.armedAt = ts; this.flight = 0; }
    if (armed && this.armedAt !== null) this.flight = (ts - this.armedAt) / 1000;
    this.wasArmed = armed;

    const data: HudData = {
      tel, gps: state?.gps ?? null, hud: this.cfg.hud, units: this.cfg.hud.units,
      armSwitch: this.cfg.mapping.arm !== null, armed: transportLive ? (live ? mapped.arm : null) : null, flip: live ? mapped.flip : null, throttle: live ? mapped.throttle : null,
      flightSeconds: this.flight, radio: (transportLive ? (state?.status ?? 'disconnected') : 'offline') as RadioState,
      track: this.track, history: this.history, tiles: this.tiles, now: ts,
    };
    const dpr = Math.max(1, window.devicePixelRatio || 1), W = this.canvas.width / dpr, H = this.canvas.height / dpr;
    const ctx = this.ctx, look = makeLook(presetById(this.cfg.hud.style ?? this.cfg.style).style, now);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0); ctx.clearRect(0, 0, W, H);

    const enabled = (Object.keys(this.cfg.hud.blocks) as Block[]).filter((b) => this.cfg.hud.blocks[b]);
    const placed = this.block === 'all' ? layoutHud(this.cfg.hud.layout, enabled, W, H) : { [this.block]: layoutSingle(this.block, W, H) };
    for (const [block, p] of Object.entries(placed) as [Block, { x: number; y: number; scale: number }][]) {
      ctx.save(); ctx.translate(p.x, p.y); ctx.scale(p.scale, p.scale);
      DRAW[block](ctx, look, data);
      ctx.restore();
    }
    if (this.block === 'all' && look.style.frame !== 'none') { // screen frame: corner brackets
      const u = Math.min(W / 1920, H / 1080), m = 14 * u;
      ctx.save(); ctx.strokeStyle = look.ring; ctx.globalAlpha = 0.45; ctx.lineWidth = Math.max(1.5, 2 * u);
      brackets(ctx, m, m, W - 2 * m, H - 2 * m, 46 * u); ctx.stroke(); ctx.restore();
    }
    scanlines(ctx, W, H, look, Math.max(1, H / 1080));
  };

  // ------------------------------------------------------------ settings panel
  private buildPanel() {
    this.panel.innerHTML = `<h3>STICKLINK · HUD</h3>
      <label>Style <select name="style"><option value="">same as main overlay</option>${PRESETS.map((p) => `<option value="${p.id}">${p.name}</option>`).join('')}</select></label>
      <label>Layout <select name="layout"><option value="corners">corners</option><option value="row">row</option><option value="column">column</option></select></label>
      <h4>BLOCKS ON THE COMBINED HUD</h4>
      <div class="row">${['link', 'battery', 'gps', 'status'].map((b) => `<label><input type="checkbox" name="block-${b}"> ${b}</label>`).join('')}</div>
      <label>Battery cells <input type="number" name="cells" min="1" max="8" step="1"></label>
      <label>Speed <select name="speed"><option value="kmh">km/h</option><option value="mph">mph</option></select></label>
      <label>Altitude <select name="alt"><option value="m">metres</option><option value="ft">feet</option></select></label>
      <h4>MAP</h4>
      <label>Tiles <select name="provider"><option value="osm">OpenStreetMap</option><option value="carto-dark">CARTO dark</option><option value="carto-light">CARTO light</option><option value="custom">custom URL</option><option value="none">no map (track only)</option></select></label>
      <label>Custom URL <input type="text" name="customUrl" placeholder="https://…/{z}/{x}/{y}.png"></label>
      <label>Credit text <input type="text" name="attribution" placeholder="shown on custom tiles"></label>
      <label>Zoom <select name="zoom"><option value="auto">auto (fit track)</option>${[12, 13, 14, 15, 16, 17, 18].map((z) => `<option value="${z}">${z}</option>`).join('')}</select></label>
      <label>Follow the quad <input type="checkbox" name="follow"></label>
      <button type="button" class="clear">Clear GPS track</button> <button type="button" class="close">Close</button> <span class="status"></span>
      <div class="hint info"></div>${LINK_HTML}`;
    this.linkRow = new LinkRow(this.panel);
    this.panel.addEventListener('input', () => this.readPanel());
    this.panel.addEventListener('change', () => this.readPanel());
    this.panel.querySelector('.close')!.addEventListener('click', () => { this.panel.hidden = true; });
    this.panel.querySelector('.clear')!.addEventListener('click', () => { void this.clearTrack(); });
    this.syncPanel();
  }

  private field(name: string) { return this.panel.querySelector(`[name="${name}"]`) as HTMLInputElement; }

  private syncPanel() {
    const h = this.cfg.hud, set = (n: string, v: string | number) => { const el = this.field(n); if (this.shadowRoot!.activeElement !== el) el.value = String(v); };
    set('style', h.style ?? ''); set('layout', h.layout); set('cells', h.cells); set('speed', h.units.speed); set('alt', h.units.alt);
    set('provider', h.map.provider); set('customUrl', h.map.customUrl); set('attribution', h.map.attribution); set('zoom', String(h.map.zoom));
    (['link', 'battery', 'gps', 'status'] as const).forEach((b) => { this.field(`block-${b}`).checked = h.blocks[b]; });
    this.field('follow').checked = h.map.follow;
    this.updateLink();
    this.panel.querySelector('.info')!.innerHTML = `This is page <b>${location.pathname}</b>. Pages: /hud, /hud/link, /hud/battery, /hud/gps. Any source size works; 1920 × 1080 for the combined HUD. ` +
      `Map tiles load from the internet: the tile server sees the area you view, and the map shows its credit. Double-click or Esc closes this panel.`;
  }

  private readPanel() {
    const f = (n: string) => this.field(n);
    const raw: any = {
      style: f('style').value || null, layout: f('layout').value, cells: f('cells').value,
      blocks: Object.fromEntries((['link', 'battery', 'gps', 'status'] as const).map((b) => [b, f(`block-${b}`).checked])),
      units: { speed: f('speed').value, alt: f('alt').value },
      map: { provider: f('provider').value, customUrl: f('customUrl').value.trim(), attribution: f('attribution').value, zoom: f('zoom').value, follow: f('follow').checked },
    };
    this.editedAt = performance.now();
    const next: HudConfig = cleanHud(raw, this.cfg.hud, STYLES);
    // a custom URL that does not validate is dropped by cleanHud; tell the user instead of silently ignoring it
    const bad = raw.map.customUrl && next.map.customUrl !== raw.map.customUrl;
    this.formError = bad ? 'Custom URL must be https:// (or http://localhost) with {z} {x} {y}: not saved' : '';
    this.panel.querySelector('.status')!.textContent = this.formError;
    this.cfg = { ...this.cfg, hud: next };
    if (!bad) this.save();
    this.updateLink();
  }

  private updateLink() { this.linkRow.update(permalink(location.origin, location.pathname, this.cfg, 'hud'), this.pinned); }
}
