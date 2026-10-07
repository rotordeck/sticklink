// /modes: pick which OBS scene a radio switch selects, like Betaflight Configurator's Modes tab.
// Scenes come from OBS; every scene is a "mode" with ranges on an AUX channel (microseconds); the server does the switching.
import { Learner, rawOf } from '../mapping.ts';
import { AUX_CHANNELS, TICKS, auxLabel, inRange, moveHandle, rangeForPosition, rawToUs, usToFrac, fracToUs, STEP, type Range } from './scale.ts';
import { DEFAULT_MODES, activeScenes, addRange, buildCards, moveMode, moveModeTo, removeRange, setRange, winner, type SceneModes } from './model.ts';
// @ts-ignore plain JS module shared with the overlays
import { StickLinkClient } from '../../../src/sticklink/web/client.js';

interface Obs { status: string; error: string; enabled: boolean; host: string; port: number; passwordSet: boolean; version: any; currentScene: string | null; scenes: string[] }
interface Engine { enabled: boolean; blocked: string | null; active: string[]; desired: string | null; committed: string | null; recent: any[]; currentScene: string | null }

const STATUS_TEXT: Record<string, string> = { disabled: 'not connected (turned off)', connecting: 'connecting…', connected: 'connected', unreachable: 'cannot reach OBS', auth_failed: 'wrong or missing password', error: 'problem' };
const BLOCKED_TEXT: Record<string, string> = { disabled: 'The scene switching below is turned off.', obs_not_connected: 'Waiting for OBS: connect it first.', no_radio_data: 'No live radio data: nothing is switched until the radio is back.' };

let cfg: SceneModes = JSON.parse(JSON.stringify(DEFAULT_MODES));
let obs: Obs | null = null;
let engine: Engine | null = null;
let hideUnused: boolean | null = null;
let learning: { scene: string; index: number; learner: Learner } | null = null;
let editedAt = -Infinity, saveTimer: any;
const client = new StickLinkClient(0);

const $ = <T extends HTMLElement>(sel: string) => document.querySelector(sel) as T;
const el = <K extends keyof HTMLElementTagNameMap>(tag: K, cls = '', text = ''): HTMLElementTagNameMap[K] => { const e = document.createElement(tag); if (cls) e.className = cls; if (text) e.textContent = text; return e; };

async function api(path: string, method = 'GET', body?: unknown) {
  const res = await fetch(path, { method, cache: 'no-store', headers: body === undefined ? {} : { 'content-type': 'application/json' }, body: body === undefined ? undefined : JSON.stringify(body) });
  const json = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(json?.error?.message ?? `HTTP ${res.status}`);
  return json;
}
const say = (text: string, bad = false) => { const s = $('#status'); s.textContent = text; s.className = bad ? 'bad' : ''; };

// ------------------------------------------------------------------ saving
function edited(next: SceneModes) { cfg = next; editedAt = performance.now(); scheduleSave(); render(); }
function scheduleSave() {
  clearTimeout(saveTimer);
  say('Saving…');
  saveTimer = setTimeout(async () => {
    try { cfg = await api('/api/v1/scene-modes', 'PUT', cfg); say('Saved ✓'); }
    catch (e: any) { say(`Not saved: ${e.message}`, true); cfg = await api('/api/v1/scene-modes'); render(); }
  }, 400);
}

// ------------------------------------------------------------------ one slider row
function sliderRow(scene: string, index: number, range: Range, refs: Ref[]): HTMLElement {
  const row = el('div', 'row');
  const chan = el('select', 'chan');
  for (const c of AUX_CHANNELS) chan.append(new Option(auxLabel(c), c, false, c === range.channel));
  chan.addEventListener('change', () => edited(setRange(cfg, scene, index, { ...range, channel: chan.value })));

  const box = el('div', 'slider'), track = el('div', 'track'), fill = el('div', 'fill'), marker = el('div', 'marker');
  const hMin = el('div', 'handle'), hMax = el('div', 'handle');
  for (const [h, name] of [[hMin, 'Minimum'], [hMax, 'Maximum']] as const) { h.tabIndex = 0; h.setAttribute('role', 'slider'); h.setAttribute('aria-label', `${scene} ${name} microseconds`); h.setAttribute('aria-valuemin', '900'); h.setAttribute('aria-valuemax', '2100'); }
  track.append(fill, marker, hMin, hMax);
  const ticks = el('div', 'ticks');
  for (const t of TICKS) { const tk = el('span', 'tick', String(t)); tk.style.left = `${usToFrac(t) * 100}%`; ticks.append(tk); }
  const vals = el('div', 'vals');
  box.append(track, ticks, vals);

  let current = range;
  const paint = () => {
    hMin.style.left = `${usToFrac(current.min) * 100}%`; hMax.style.left = `${usToFrac(current.max) * 100}%`;
    fill.style.left = `${usToFrac(current.min) * 100}%`; fill.style.width = `${(usToFrac(current.max) - usToFrac(current.min)) * 100}%`;
    hMin.setAttribute('aria-valuenow', String(current.min)); hMax.setAttribute('aria-valuenow', String(current.max));
    vals.textContent = `Min: ${current.min}   Max: ${current.max}`;
  };
  paint();
  const commit = (next: Range) => { current = next; paint(); editedAt = performance.now(); cfg = setRange(cfg, scene, index, next); scheduleSave(); };
  for (const [h, which] of [[hMin, 'min'], [hMax, 'max']] as const) {
    h.addEventListener('pointerdown', (e) => {
      e.preventDefault(); h.setPointerCapture(e.pointerId); h.classList.add('drag');
      const move = (ev: PointerEvent) => { const r = track.getBoundingClientRect(); commit(moveHandle(current, which, fracToUs((ev.clientX - r.left) / r.width))); };
      const up = () => { h.classList.remove('drag'); h.removeEventListener('pointermove', move); h.removeEventListener('pointerup', up); h.removeEventListener('pointercancel', up); render(); };
      h.addEventListener('pointermove', move); h.addEventListener('pointerup', up); h.addEventListener('pointercancel', up);
    });
    h.addEventListener('keydown', (e) => {
      const step = e.key === 'ArrowRight' || e.key === 'ArrowUp' ? STEP : e.key === 'ArrowLeft' || e.key === 'ArrowDown' ? -STEP : e.key === 'PageUp' ? 4 * STEP : e.key === 'PageDown' ? -4 * STEP : 0;
      if (e.key === 'Home' || e.key === 'End') { e.preventDefault(); commit(moveHandle(current, which, e.key === 'Home' ? 900 : 2100)); return; }
      if (!step) return;
      e.preventDefault(); commit(moveHandle(current, which, current[which] + step));
    });
  }
  track.addEventListener('pointerdown', (e) => { // a click on the bar moves the nearer handle there
    if (e.target !== track && e.target !== fill) return;
    const r = track.getBoundingClientRect(), us = fracToUs((e.clientX - r.left) / r.width);
    commit(moveHandle(current, Math.abs(us - current.min) <= Math.abs(us - current.max) ? 'min' : 'max', us));
  });

  const learn = el('button', 'btn small', learning?.scene === scene && learning.index === index ? 'Listening…' : 'Learn');
  learn.title = 'Move a switch to the position that should select this scene';
  learn.addEventListener('click', () => { learning = learning?.scene === scene && learning.index === index ? null : { scene, index, learner: new Learner(AUX_CHANNELS) }; render(); });
  const del = el('button', 'btn small x', '×'); del.title = 'Remove this range';
  del.addEventListener('click', () => edited(removeRange(cfg, scene, index)));
  row.append(chan, box, learn, del);
  refs.push({ channel: range.channel, fill, marker, row, range: () => current });
  return row;
}
interface Ref { channel: string; fill: HTMLElement; marker: HTMLElement; row: HTMLElement; range: () => Range }
let refs: Ref[] = [];
let cardRefs: { scene: string; card: HTMLElement; used: boolean; tag: HTMLElement }[] = [];

// ------------------------------------------------------------------ cards
function render() {
  const cards = buildCards(cfg, obs && obs.status === 'connected' ? obs.scenes : obs?.scenes?.length ? obs.scenes : null, hideUnused ?? false);
  refs = []; cardRefs = [];
  const list = $('#cards'); list.replaceChildren();
  if (!cards.length) list.append(el('div', 'empty', obs?.status === 'connected' ? 'Every scene is hidden. Untick “Hide unused modes” to add ranges.' : 'Connect OBS above to load your scenes here.'));
  for (const c of cards) {
    const card = el('div', 'card' + (c.used ? '' : ' unused'));
    const head = el('div', 'head'), name = el('div', 'name', c.scene);
    if (c.inObs === false) name.append(el('span', 'tag', 'not in OBS'));
    head.append(name);
    const tag = el('div', 'winner'); head.append(tag);
    if (c.used) {
      const pr = el('div', 'prio'); pr.append(el('span', 'num', `#${c.priority}`));
      const grip = el('span', 'grip', '⠿ drag'); grip.title = 'Drag up or down to sort. When several scenes are active, the upper one wins.';
      grip.addEventListener('pointerdown', (e) => startSort(e, c.scene, grip));
      pr.append(grip);
      const up = el('button', 'btn tiny', '▲'), down = el('button', 'btn tiny', '▼'); up.title = 'Higher priority'; down.title = 'Lower priority';
      up.addEventListener('click', () => edited(moveMode(cfg, c.scene, -1))); down.addEventListener('click', () => edited(moveMode(cfg, c.scene, 1)));
      pr.append(up, down); head.append(pr);
    }
    const show = el('button', 'btn small', 'Show in OBS'); show.title = 'Switch OBS to this scene now (a test)';
    show.addEventListener('click', async () => { try { await api('/api/v1/obs/scene', 'POST', { scene: c.scene }); say(`OBS is now showing “${c.scene}”`); } catch (e: any) { say(e.message, true); } });
    const add = el('button', 'btn small primary', 'Add Range'); add.addEventListener('click', () => edited(addRange(cfg, c.scene)));
    head.append(show, add);
    const ranges = el('div', 'ranges');
    c.ranges.forEach((r, i) => ranges.append(sliderRow(c.scene, i, r, refs)));
    card.append(head, ranges); list.append(card); cardRefs.push({ scene: c.scene, card, used: c.used, tag });
  }
  // engine settings
  ($('#enabled') as HTMLInputElement).checked = cfg.enabled;
  ($('#debounce') as HTMLInputElement).value = String(cfg.debounceMs);
  const sel = $('#whenNone') as HTMLSelectElement, sc = $('#whenScene') as HTMLSelectElement;
  sel.value = cfg.whenNone.action;
  const names = [...new Set([...(obs?.scenes ?? []), ...cfg.modes.map((m) => m.scene)])];
  sc.replaceChildren(...names.map((n) => new Option(n, n, false, n === cfg.whenNone.scene)));
  sc.hidden = cfg.whenNone.action !== 'scene';
  ($('#hideUnused') as HTMLInputElement).checked = hideUnused ?? false;
  $('#banner').hidden = !learning;
  if (learning) $('#banner').textContent = `Move the switch for “${learning.scene}” to the position that should select it… (Esc to cancel)`;
}

// ------------------------------------------------------------------ sorting
/** Drag a mode card up or down; the position it is dropped at is its new priority (top = wins). */
function startSort(e: PointerEvent, scene: string, grip: HTMLElement) {
  e.preventDefault(); grip.setPointerCapture(e.pointerId);
  const used = cardRefs.filter((c) => c.used), me = used.find((c) => c.scene === scene)!;
  me.card.classList.add('dragging');
  const target = (y: number) => used.filter((c) => c !== me && (() => { const r = c.card.getBoundingClientRect(); return r.top + r.height / 2 < y; })()).length;
  const mark = (index: number) => { used.forEach((c) => c.card.classList.remove('drop-before', 'drop-after')); const others = used.filter((c) => c !== me); if (index < others.length) others[index].card.classList.add('drop-before'); else others.at(-1)?.card.classList.add('drop-after'); };
  let index = target(e.clientY);
  mark(index);
  const move = (ev: PointerEvent) => { index = target(ev.clientY); mark(index); };
  const up = () => {
    grip.removeEventListener('pointermove', move); grip.removeEventListener('pointerup', up); grip.removeEventListener('pointercancel', up);
    const from = cfg.modes.findIndex((m) => m.scene === scene);
    if (index !== from) edited(moveModeTo(cfg, scene, index)); else render();
  };
  grip.addEventListener('pointermove', move); grip.addEventListener('pointerup', up); grip.addEventListener('pointercancel', up);
}

// ------------------------------------------------------------------ live updates
function usMap(state: any): Record<string, number | null> {
  const out: Record<string, number | null> = {};
  for (const c of AUX_CHANNELS) { const raw = rawOf(state, c); out[c] = raw === null ? null : rawToUs(raw); }
  return out;
}

function frame(ts: number) {
  requestAnimationFrame(frame);
  const { state, transportLive } = client.step();
  const us = usMap(transportLive ? state : null), active = new Set(activeScenes(cfg, us));
  for (const r of refs) {
    const v = us[r.channel];
    r.marker.hidden = v == null; if (v != null) { r.marker.style.left = `${usToFrac(v) * 100}%`; r.marker.title = `${v} µs`; }
    const on = inRange(v, r.range()); r.row.classList.toggle('on', on); r.fill.classList.toggle('on', on);
  }
  const activeList = activeScenes(cfg, us), top = winner(activeList);
  for (const c of cardRefs) {
    c.card.classList.toggle('active', active.has(c.scene));
    c.card.classList.toggle('selected', c.scene === top);
    c.tag.textContent = c.scene === top ? (activeList.length > 1 ? '▶ SELECTED (upper wins)' : '▶ SELECTED') : active.has(c.scene) ? 'also active, lower priority' : '';
  }
  if (learning) {
    const res = learning.learner.update(transportLive ? state : null, ts);
    if (res) {
      const v = rawToUs(res.level); const l = learning; learning = null;
      edited(setRange(cfg, l.scene, l.index, rangeForPosition(res.src, v)));
    }
  }
}

function paintStatus() {
  const dot = $('#dot'), t = $('#obsText');
  const s = obs?.status ?? 'disabled';
  dot.className = `dot ${s}`;
  t.textContent = obs ? `OBS: ${STATUS_TEXT[s] ?? s}${s === 'connected' ? ` · ${obs.version?.obsVersion ? 'OBS ' + obs.version.obsVersion + ' · ' : ''}live scene: ${obs.currentScene ?? '?'}` : obs.error ? ` · ${obs.error}` : ''}` : 'OBS: …';
  const e = engine, line = $('#engine');
  if (!e) { line.textContent = ''; return; }
  const parts = [e.blocked ? BLOCKED_TEXT[e.blocked] : `Live. The radio asks for: ${e.desired ?? '(no mode active)'}.`];
  const last = e.recent.at(-1);
  if (last) parts.push(`Last switch: ${new Date(last.t * 1000).toLocaleTimeString()} → ${last.scene}${last.ok === false ? ` (failed: ${last.error})` : ''}.`);
  line.textContent = parts.join(' ');
  line.className = e.blocked ? 'blocked' : 'live';
}

async function poll() {
  try { obs = await api('/api/v1/obs'); engine = await api('/api/v1/scene-modes/state'); paintStatus(); }
  catch { obs = null; $('#obsText').textContent = 'Sticklink is not reachable.'; }
  if (obs && !($('#host') as HTMLInputElement).dataset.touched) { ($('#host') as HTMLInputElement).value = obs.host; ($('#port') as HTMLInputElement).value = String(obs.port); ($('#pw') as HTMLInputElement).placeholder = obs.passwordSet ? '(stored: leave empty to keep it)' : 'empty if OBS has no password'; ($('#obsOn') as HTMLInputElement).checked = obs.enabled; }
  if (performance.now() - editedAt > 2500) { try { const server = await api('/api/v1/scene-modes'); if (JSON.stringify(server) !== JSON.stringify(cfg)) { cfg = server; render(); } } catch { /* keep */ } }
  renderIfScenesChanged();
}
let lastScenes = '';
function renderIfScenesChanged() { const key = JSON.stringify(obs?.scenes ?? []); if (key !== lastScenes) { lastScenes = key; render(); } }

// ------------------------------------------------------------------ boot
function build() {
  document.body.append(Object.assign(el('main'), { innerHTML: `
    <header><h1><img src="/assets/icon.svg" alt="">Sticklink <small>Modes</small></h1><nav><a href="/setup">Setup</a><a href="/hud">HUD</a><a href="/fx">Overlay</a><a href="/docs">API</a></nav><span id="status"></span></header>
    <section class="panel"><div class="obsline"><span id="dot" class="dot"></span><b id="obsText">OBS: …</b>
      <button class="btn small" id="toggleConn">Connection…</button><button class="btn small" id="refresh">Refresh scenes</button></div>
      <div id="conn" hidden>
        <label>Host <input id="host" size="16" spellcheck="false"></label><label>Port <input id="port" type="number" min="1" max="65535" style="width:5em"></label>
        <label>Password <input id="pw" type="password" autocomplete="off" size="22"></label>
        <label class="check"><input id="obsOn" type="checkbox"> Connect to OBS</label><button class="btn primary small" id="saveConn">Save &amp; connect</button>
        <div class="hint">In OBS: Tools → WebSocket Server Settings → Enable WebSocket server (port 4455 by default). The password is stored in a file only you can read and is never shown again.</div>
      </div></section>
    <section class="panel"><label class="switch"><input id="enabled" type="checkbox"> <b>Switch scenes from the radio</b></label>
      <div class="warn">When on, moving a switch changes your <b>live</b> OBS scene. Turning it on adopts the switch positions as they are (nothing changes by itself), and nothing is switched while the radio data is stale or OBS is away.</div>
      <div id="engine"></div>
      <div class="opts"><label>When no mode is active <select id="whenNone"><option value="stay">stay on the current scene</option><option value="previous">return to the previous scene</option><option value="scene">go to…</option></select>
        <select id="whenScene" hidden></select></label>
        <label>Settle time <input id="debounce" type="number" min="0" max="2000" step="10" style="width:5em"> ms</label>
        <button class="btn small" id="apply" title="Switch OBS to what the switches ask for right now">Apply now</button></div></section>
    <div class="info">Set up <b>ranges</b> to select a scene with a switch or button. A scene is active while its channel is inside one of its ranges (1000 = switch low, 1500 = middle, 2000 = high). If several scenes are active at once, <b>the upper one wins</b>: drag a mode by its ⠿ grip (or use ▲ ▼) to sort the list. The orange marker shows where your switch is right now. <b>Learn</b> picks a channel by flipping the switch.</div>
    <div id="banner" hidden></div>
    <label class="check hide"><input id="hideUnused" type="checkbox"> <b>Hide unused modes</b></label>
    <div id="cards"></div>` }));
  $('#toggleConn').addEventListener('click', () => { const c = $('#conn'); c.hidden = !c.hidden; });
  $('#refresh').addEventListener('click', () => { void poll(); });
  for (const id of ['host', 'port', 'pw']) $('#' + id).addEventListener('input', () => { ($('#host') as HTMLInputElement).dataset.touched = '1'; });
  $('#saveConn').addEventListener('click', async () => {
    const body: any = { enabled: ($('#obsOn') as HTMLInputElement).checked, host: ($('#host') as HTMLInputElement).value.trim(), port: Number(($('#port') as HTMLInputElement).value) };
    const pw = ($('#pw') as HTMLInputElement).value; if (pw !== '') body.password = pw;
    try { obs = await api('/api/v1/obs/connection', 'PATCH', body); delete ($('#host') as HTMLInputElement).dataset.touched; ($('#pw') as HTMLInputElement).value = ''; say('Connection saved ✓'); paintStatus(); }
    catch (e: any) { say(e.message, true); }
  });
  $('#enabled').addEventListener('change', (e) => edited({ ...cfg, enabled: (e.target as HTMLInputElement).checked }));
  $('#debounce').addEventListener('change', (e) => edited({ ...cfg, debounceMs: Math.max(0, Math.min(2000, Number((e.target as HTMLInputElement).value) || 0)) }));
  const whenChanged = () => {
    const action = ($('#whenNone') as HTMLSelectElement).value as SceneModes['whenNone']['action'], sc = ($('#whenScene') as HTMLSelectElement).value || obs?.scenes?.[0] || null;
    if (action === 'scene' && !sc) { say('Connect OBS first: there is no scene to go to.', true); render(); return; }
    edited({ ...cfg, whenNone: { action, scene: action === 'scene' ? sc : null } });
  };
  $('#whenNone').addEventListener('change', whenChanged); $('#whenScene').addEventListener('change', whenChanged);
  $('#hideUnused').addEventListener('change', (e) => { hideUnused = (e.target as HTMLInputElement).checked; render(); });
  $('#apply').addEventListener('click', async () => { try { const r = await api('/api/v1/scene-modes/apply', 'POST', {}); say(`OBS is now showing “${r.scene}”`); } catch (e: any) { say(e.message, true); } });
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && learning) { learning = null; render(); } });
}

async function start() {
  build();
  try { cfg = await api('/api/v1/scene-modes'); } catch { /* the page still renders */ }
  hideUnused = cfg.modes.length > 0; // a first-time user sees every scene; once modes exist, only those
  await poll(); render();
  client.start();
  setInterval(poll, 1500);
  requestAnimationFrame(frame);
}
void start();
