import { PRESETS, presetById } from './render/style.ts';
import { computeLayout, DEFAULT_SETTINGS, type Settings } from './render/layout.ts';
import { createScene, renderFrame, type Scene } from './render/draw.ts';
import { LiveFeed, rendererMode, type LiveFrame } from './live.ts';
import { DEFAULTS, clean, type FxConfig } from './config.ts';
import { PARAM, decodeConfig, permalink } from './permalink.ts';
import { LINK_CSS, LINK_HTML, LinkRow } from './permalink-ui.ts';
import { applyMapping } from './mapping.ts';
// @ts-ignore plain JS module shared with the classic overlay
import { StickLinkClient } from '../../src/sticklink/web/client.js';

const FPS = 60;
const GIMBAL = 0.17; // gimbal box as a fraction of the reference size (stickcam's layout)
const FONTS = ['16px Bungee', 'italic 900 16px Orbitron', '700 16px Fredoka', '16px VT323'];
const STYLES = PRESETS.map((p) => p.id);

export class StickFx extends HTMLElement {
  private cfg: FxConfig = { ...DEFAULTS };
  private canvas = document.createElement('canvas');
  private badge = document.createElement('div');
  private panel = document.createElement('div');
  private client: any;
  private feed!: LiveFeed;
  private scene!: Scene;
  private settings!: Settings;
  private builtSize = 0; private resizeTimer = 0;
  private ctx = this.canvas.getContext('2d')!;
  private acc = 0; private lastTs = 0; private raf = 0; private ready = false;
  private lastState: any = null; private lastSession: unknown = null; private lastSampleT = -Infinity;
  private pendingT: number | undefined; private latest: ReturnType<typeof applyMapping> | null = null;
  private serverJson = ''; private poll: any; private saveTimer: any;
  private editedAt = -Infinity; // when the user last changed a setting here: polled server settings must not overwrite a fresh edit
  private pinned = false; // opened from a ?cfg= link: use exactly that, never touch the server's saved settings
  private linkRow!: LinkRow;

  constructor() {
    super();
    const root = this.attachShadow({ mode: 'open' });
    root.innerHTML = `<style>
      :host{display:block;position:fixed;inset:0}canvas{display:block}
      .panel{position:fixed;inset:8px auto auto 8px;max-width:min(340px,calc(100vw - 16px));max-height:calc(100vh - 16px);overflow:auto;
        box-sizing:border-box;padding:12px 14px;border-radius:10px;background:#0b1420f2;border:1px solid #7d94ac66;color:#e6eef7;
        font:12px/1.4 Arial,sans-serif;z-index:10}
      .panel[hidden]{display:none}h3{margin:0 0 8px;font-size:13px;letter-spacing:1px}
      label{display:flex;align-items:center;justify-content:space-between;gap:8px;margin:6px 0}
      select,input[type=number]{background:#16273a;color:inherit;border:1px solid #4a6078;border-radius:4px;padding:3px 5px;font:inherit;max-width:60%}
      input[type=range]{width:55%}.row{display:flex;gap:10px;flex-wrap:wrap}.row label{margin:2px 0;gap:4px}
      .blurb{color:#9fb2c4;font-size:11px;margin:-2px 0 6px}.hint{color:#9fb2c4;font-size:11px;margin-top:8px}
      button{margin-top:8px;background:#16273a;color:inherit;border:1px solid #4a6078;border-radius:4px;padding:4px 10px;font:inherit;cursor:pointer}
      .status{color:#50e0c1}a{color:#50e0c1}${LINK_CSS}
      .badge{position:absolute;left:50%;top:6px;transform:translateX(-50%);padding:3px 12px;border-radius:6px;background:#ff3b3bd9;color:#fff;
        font:700 13px Arial,sans-serif;letter-spacing:2px;pointer-events:none}.badge[hidden]{display:none}
    </style>`;
    this.panel.className = 'panel'; this.panel.hidden = true;
    this.badge.className = 'badge'; this.badge.textContent = 'CRASH FLIP'; this.badge.hidden = true;
    root.append(this.canvas, this.badge, this.panel);
    this.panel.addEventListener('dblclick', (e) => e.stopPropagation());
  }

  async connectedCallback() {
    const q = new URLSearchParams(location.search);
    const link = decodeConfig(q.get(PARAM));
    this.pinned = link !== null;
    if (link) this.cfg = clean(link, DEFAULTS, STYLES); // a link is applied on the defaults, independent of what is saved
    else {
      this.cfg = clean(Object.fromEntries(q.entries()), DEFAULTS, STYLES);
      await this.fetchConfig();
    }
    this.buildPanel();
    this.rebuild();
    this.client = new StickLinkClient(this.cfg.delay);
    this.client.start();
    window.addEventListener('resize', this.onResize);
    document.addEventListener('dblclick', this.toggle);
    document.addEventListener('keydown', this.onKey);
    if (!this.pinned) this.poll = setInterval(() => { if (performance.now() - this.editedAt > 2500) void this.fetchConfig().then((changed) => changed && this.apply()); }, 2000);
    Promise.race([Promise.all(FONTS.map((f) => document.fonts.load(f))), new Promise((r) => setTimeout(r, 3000))])
      .catch(() => {}).finally(() => { this.ready = true; });
    this.raf = requestAnimationFrame(this.tick);
  }

  disconnectedCallback() {
    cancelAnimationFrame(this.raf); clearInterval(this.poll);
    window.removeEventListener('resize', this.onResize);
    document.removeEventListener('dblclick', this.toggle); document.removeEventListener('keydown', this.onKey);
    this.client?.stop();
  }

  private onResize = () => { cancelAnimationFrame(this.resizeTimer); this.resizeTimer = requestAnimationFrame(() => this.buildScene()); };
  private toggle = () => { this.panel.hidden = !this.panel.hidden; if (!this.panel.hidden) this.syncPanel(); };
  private onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') this.panel.hidden = true; };

  /** Pull the server-stored config (wins over URL seeds). Returns true if it changed. */
  private async fetchConfig(): Promise<boolean> {
    try {
      const res = await fetch('/api/fx-config', { cache: 'no-store' });
      const text = await res.text();
      if (!res.ok || text === this.serverJson) return false;
      this.serverJson = text;
      this.cfg = clean(JSON.parse(text), this.cfg, STYLES);
      return true;
    } catch { return false; }
  }

  private save() {
    clearTimeout(this.saveTimer);
    if (this.pinned) { this.panel.querySelector('.status')!.textContent = 'Not saved on the server (opened from a link)'; return; }
    this.saveTimer = setTimeout(async () => {
      const status = this.panel.querySelector('.status')!;
      try {
        const res = await fetch('/api/fx-config', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(this.cfg) });
        if (res.ok) this.serverJson = await fetch('/api/fx-config', { cache: 'no-store' }).then((r) => r.text());
        status.textContent = res.ok ? 'Saved' : 'Could not save';
      } catch { status.textContent = 'Could not save'; }
    }, 300);
  }

  /** Apply this.cfg: cheap changes in place, mode/size by rebuilding the scene. */
  private apply() {
    if (this.cfg.mode !== this.feed.mode) this.rebuild();
    else if (this.cfg.size !== this.builtSize) this.buildScene();
    this.scene.style = presetById(this.cfg.style).style;
    this.settings.chaos = this.cfg.chaos;
    this.client.delayMs = this.cfg.delay;
    this.syncPanel();
  }

  /** New stick history (mode changed) and a scene to match. */
  private rebuild() {
    this.feed = new LiveFeed(FPS, this.cfg.mode);
    this.acc = 0;
    this.buildScene();
  }

  /**
   * The overlay fills the whole page (the OBS source, whatever size it has) and the gimbals sit in its middle, so a
   * source that is bigger or smaller than the recommended size is still centred. It shrinks if the source is small.
   */
  private buildScene() {
    const vw = Math.max(64, window.innerWidth || 576), vh = Math.max(64, window.innerHeight || 450);
    const gap = DEFAULT_SETTINGS.gap;
    const g = Math.min(this.cfg.size * GIMBAL, (0.94 * vw) / (2 + gap), 0.6 * vh); // wanted size, limited to what fits
    this.settings = { ...DEFAULT_SETTINGS, crop: false, width: vw, height: vh, position: 'middle', size: g / Math.min(vw, vh), gap,
      mode: rendererMode(this.cfg.mode), chaos: this.cfg.chaos, fps: FPS };
    const scale = Math.max(1, window.devicePixelRatio || 1);
    this.scene = createScene(this.feed.track, this.feed.motion, presetById(this.cfg.style).style, this.settings, scale);
    const L = this.scene.layout;
    this.canvas.width = Math.round(L.W * scale); this.canvas.height = Math.round(L.H * scale);
    this.canvas.style.width = `${L.W}px`; this.canvas.style.height = `${L.H}px`;
    this.builtSize = this.cfg.size;
  }

  private tick = (ts: number) => {
    this.raf = requestAnimationFrame(this.tick);
    this.acc += Math.min(0.25, this.lastTs ? (ts - this.lastTs) / 1000 : 1 / FPS); this.lastTs = ts;
    const { state, transportLive } = this.client.step();
    const mapped = applyMapping(state, this.cfg.mapping);
    if (!(transportLive && mapped.live)) { this.latest = null; this.pendingT = undefined; this.lastState = null; }
    else {
      this.latest = mapped;
      if (state !== this.lastState) { // a new bridge snapshot: is it a new radio reading?
        this.lastState = state;
        const t = state.tick * 10; // radio ticks are 10 ms
        if (state.session !== this.lastSession || t < this.lastSampleT - 1000) { this.feed.breakReadings(); this.lastSession = state.session; this.lastSampleT = -Infinity; }
        if (t > this.lastSampleT) { this.lastSampleT = t; this.pendingT = t; }
      }
    }
    const rest: LiveFrame = { live: false, roll: 0, pitch: 0, yaw: 0, throttle: 0, armed: null };
    const frame = (): LiveFrame => this.latest
      ? { live: true, roll: this.latest.roll, pitch: this.latest.pitch, yaw: this.latest.yaw, throttle: this.latest.throttle, armed: this.latest.arm }
      : rest;
    let pushed = 0;
    while (this.acc >= 1 / FPS && pushed < 8) {
      this.acc -= 1 / FPS; pushed++;
      this.feed.push(frame(), this.latest ? this.pendingT : undefined); this.pendingT = undefined;
    }
    if (pushed === 8) this.acc = 0;
    if (!this.feed.frames) this.feed.push(frame());
    this.badge.hidden = !(this.latest && this.latest.flip);
    if (this.ready) renderFrame(this.ctx, this.scene, this.feed.frames - 1);
  };

  private buildPanel() {
    this.panel.innerHTML = `<h3>STICKLINK · SETTINGS</h3>
      <label>Style <select name="style">${PRESETS.map((p) => `<option value="${p.id}">${p.name}</option>`).join('')}</select></label>
      <div class="blurb"></div>
      <label>Effects <input type="range" name="chaos" min="0" max="2" step="0.05"><span class="chaosv"></span></label>
      <label>Video delay (ms) <input type="number" name="delay" min="0" max="5000" step="10"></label>
      <label>Size (px) <input type="number" name="size" min="240" max="2160" step="10"></label>
      <div class="hint"><a href="/setup" target="_blank">Stick layout, sticks, ARM and crash flip: open /setup…</a></div>
      <div class="hint info"></div>${LINK_HTML}
      <button type="button" class="close">Close</button> <span class="status"></span>`;
    this.linkRow = new LinkRow(this.panel);
    this.panel.addEventListener('input', () => this.readPanel());
    this.panel.addEventListener('change', () => this.readPanel());
    this.panel.querySelector('.close')!.addEventListener('click', () => { this.panel.hidden = true; });
  }

  private field(name: string) { return this.panel.querySelector(`[name="${name}"]`) as HTMLInputElement; }

  private syncPanel() {
    const c = this.cfg, set = (n: string, v: string | number) => { const el = this.field(n); if (document.activeElement !== el && el.value !== String(v)) el.value = String(v); };
    (['style', 'chaos', 'delay', 'size'] as const).forEach((k) => set(k, c[k]));
    this.panel.querySelector('.blurb')!.textContent = presetById(c.style).blurb;
    this.panel.querySelector('.chaosv')!.textContent = c.chaos.toFixed(2);
    this.updateLink();
    const tight = computeLayout({ ...DEFAULT_SETTINGS, crop: true, cropRef: c.size });
    this.panel.querySelector('.info')!.textContent = `Recommended OBS Browser Source size: ${tight.W} × ${tight.H} (any size works: the overlay centres itself). Double-click or Esc closes this panel. Changes save automatically.`;
  }

  private readPanel() {
    const raw: Record<string, unknown> = {
      style: this.field('style').value, chaos: this.field('chaos').value,
      delay: this.field('delay').value, size: this.field('size').value,
    };
    this.editedAt = performance.now();
    this.cfg = clean(raw, this.cfg, STYLES);
    this.apply(); this.save();
    this.updateLink();
  }

  private updateLink() { this.linkRow.update(permalink(location.origin, location.pathname, this.cfg, 'fx'), this.pinned); }
}
