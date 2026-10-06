// /setup: the receiver screen. Live model + bars, channel monitor, and mapping with "learn by moving it".
import { PRESETS } from './render/style.ts';
import { DEFAULTS, clean, type FxConfig } from './config.ts';
import { drawDrone } from './drone3d.ts';
import {
  ALL_SOURCES, AXIS_NAMES, DEFAULT_MAPPING, SWITCH_SOURCES, Learner, applyMapping, axisFromLearn, norm, rawOf, srcLabel,
  switchFromLearn, type AxisName, type Src,
} from './mapping.ts';
// @ts-ignore plain JS module shared with the overlays
import { StickLinkClient } from '../../src/sticklink/web/client.js';

const STYLES = PRESETS.map((p) => p.id);
const PROMPT: Record<AxisName, string> = {
  roll: 'Push the ROLL stick fully RIGHT and hold it',
  pitch: 'Push the PITCH stick fully UP (forward) and hold it',
  yaw: 'Push the YAW stick fully RIGHT and hold it',
  throttle: 'Push the THROTTLE stick fully UP and hold it',
};
const AXIS_SOURCES: Src[] = ALL_SOURCES.filter((s) => !['in:arm', 'in:crash'].includes(s));
const SWITCH_LEARN: Src[] = SWITCH_SOURCES.filter((s) => !['ch:1', 'ch:2', 'ch:3', 'ch:4'].includes(s));
const MODES = [
  [1, 'Mode 1', 'Left: yaw + pitch · Right: roll + throttle'], [2, 'Mode 2', 'Left: yaw + throttle · Right: roll + pitch'],
  [3, 'Mode 3', 'Left: roll + pitch · Right: yaw + throttle'], [4, 'Mode 4', 'Left: roll + throttle · Right: yaw + pitch'],
] as const;

const $ = <T extends HTMLElement>(sel: string) => document.querySelector(sel) as T;
const h = (html: string) => { const t = document.createElement('template'); t.innerHTML = html.trim(); return t.content.firstElementChild as HTMLElement; };

let cfg: FxConfig = { ...DEFAULTS };
let learning: { kind: 'axis' | 'switch'; target: string; learner: Learner; since: number } | null = null;
let saveTimer: any, yawAngle = 0, spin = 0, last = performance.now();
const client = new StickLinkClient(0);

async function load() {
  try { cfg = clean(await (await fetch('/api/fx-config', { cache: 'no-store' })).json(), DEFAULTS, STYLES); } catch { /* defaults */ }
}
function save() {
  clearTimeout(saveTimer);
  saveTimer = setTimeout(async () => {
    const note = $('#saved');
    try {
      const res = await fetch('/api/fx-config', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ mapping: cfg.mapping, mode: cfg.mode }) });
      note.textContent = res.ok ? 'Saved ✓' : `Could not save: ${await res.text()}`;
    } catch { note.textContent = 'Could not save (is sticklink running?)'; }
  }, 250);
}

function build() {
  document.body.append(h(`<main>
    <header><h1>STICKLINK · SETUP</h1><span id="conn">CONNECTING</span><span id="saved"></span></header>
    <div id="banner" hidden></div>
    <section class="cols">
      <div class="col"><canvas id="drone" width="380" height="280"></canvas>
        <div id="bars"></div>
        <div class="lamps"><span id="armLamp" class="lamp">ARM</span><span id="flipLamp" class="lamp">CRASH FLIP</span></div>
        <label class="mode">Stick layout <select id="mode">${MODES.map(([v, n]) => `<option value="${v}">${n}</option>`).join('')}</select></label>
        <div id="modeHint" class="hint"></div>
      </div>
      <div class="col"><h2>Assign sticks</h2><div id="axes"></div><h2>Assign switches</h2><div id="switches"></div>
        <div class="hint">Press <b>Learn</b>, then move the control. The page picks whichever input moved. For a switch: put it in the OFF position first, press Learn, then flip it ON.</div>
        <button id="reset" type="button">Reset to defaults</button> <a href="/fx" target="_blank">Open overlay</a></div>
    </section>
    <h2>Channel monitor</h2><div id="mon"></div>
  </main>`));
  const axes = $('#axes');
  for (const a of AXIS_NAMES) {
    axes.append(h(`<div class="row" data-axis="${a}"><b>${a.toUpperCase()}</b>
      <select>${AXIS_SOURCES.map((s) => `<option value="${s}">${srcLabel(s)}</option>`).join('')}</select>
      <label><input type="checkbox" class="rev"> reverse</label><button type="button" class="learn">Learn</button><div class="meter"><i></i></div></div>`));
  }
  const sw = $('#switches');
  for (const k of ['arm', 'flip'] as const) {
    sw.append(h(`<div class="row" data-sw="${k}"><b>${k === 'arm' ? 'ARM' : 'CRASH FLIP'}</b>
      <select>${k === 'flip' ? '<option value="">— none —</option>' : ''}${SWITCH_SOURCES.map((s) => `<option value="${s}">${srcLabel(s)}</option>`).join('')}</select>
      <label>active when <select class="dir"><option value="1">high</option><option value="-1">low</option></select></label>
      <button type="button" class="learn">Learn</button><div class="meter"><i></i></div></div>`));
  }
  $('#bars').append(...AXIS_NAMES.map((a) => h(`<div class="bar" data-bar="${a}"><span>${a}</span><div class="meter"><i></i></div><em>0</em></div>`)));
  $('#mon').append(...Array.from({ length: 16 }, (_, i) => h(`<div class="bar" data-ch="${i + 1}"><span>${srcLabel(`ch:${i + 1}`)}</span><div class="meter"><i></i></div><em>—</em></div>`)));

  document.addEventListener('change', onChange);
  document.addEventListener('click', onClick);
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape') stopLearn(); });
  refreshForm();
}

function refreshForm() {
  for (const a of AXIS_NAMES) {
    const row = $(`[data-axis="${a}"]`);
    (row.querySelector('select') as HTMLSelectElement).value = cfg.mapping[a].src;
    (row.querySelector('.rev') as HTMLInputElement).checked = cfg.mapping[a].rev;
  }
  for (const k of ['arm', 'flip'] as const) {
    const row = $(`[data-sw="${k}"]`), m = cfg.mapping[k];
    (row.querySelector('select') as HTMLSelectElement).value = m?.src ?? '';
    (row.querySelector('.dir') as HTMLSelectElement).value = String(m?.dir ?? 1);
  }
  ($('#mode') as HTMLSelectElement).value = String(cfg.mode);
  $('#modeHint').textContent = MODES.find((m) => m[0] === cfg.mode)![2];
}

function onChange(e: Event) {
  const el = e.target as HTMLElement, row = el.closest('[data-axis],[data-sw]') as HTMLElement | null;
  if (el.id === 'mode') { cfg.mode = Number((el as HTMLSelectElement).value) as FxConfig['mode']; }
  else if (row?.dataset.axis) {
    const a = row.dataset.axis as AxisName;
    cfg.mapping[a] = { src: (row.querySelector('select') as HTMLSelectElement).value, rev: (row.querySelector('.rev') as HTMLInputElement).checked };
  } else if (row?.dataset.sw) {
    const k = row.dataset.sw as 'arm' | 'flip', src = (row.querySelector('select') as HTMLSelectElement).value;
    const dir = Number((row.querySelector('.dir') as HTMLSelectElement).value) as 1 | -1, prev = cfg.mapping[k];
    cfg.mapping[k] = src ? { src, thr: prev?.src === src ? prev.thr : 0, dir } : null;
  } else return;
  refreshForm(); save();
}

function onClick(e: MouseEvent) {
  const el = e.target as HTMLElement;
  if (el.id === 'reset') { cfg.mapping = JSON.parse(JSON.stringify(DEFAULT_MAPPING)); cfg.mode = 2; refreshForm(); save(); return; }
  if (!el.classList.contains('learn')) return;
  const row = el.closest('[data-axis],[data-sw]') as HTMLElement, axis = row.dataset.axis as AxisName | undefined;
  stopLearn();
  learning = axis
    ? { kind: 'axis', target: axis, learner: new Learner(AXIS_SOURCES), since: performance.now() }
    : { kind: 'switch', target: row.dataset.sw!, learner: new Learner(SWITCH_LEARN), since: performance.now() };
  el.textContent = 'Listening… (Esc to cancel)';
  const banner = $('#banner'); banner.hidden = false;
  banner.textContent = axis ? PROMPT[axis] : 'Switch is OFF? Now flip it ON and leave it there';
}

function stopLearn() {
  learning = null; $('#banner').hidden = true;
  document.querySelectorAll('.learn').forEach((b) => { b.textContent = 'Learn'; });
}

const setMeter = (el: Element, v: number, centered = true) => {
  const i = el.querySelector('i') as HTMLElement;
  if (centered) { i.style.left = `${50 + Math.min(0, v) * 50}%`; i.style.width = `${Math.abs(v) * 50}%`; }
  else { i.style.left = '0'; i.style.width = `${v * 100}%`; }
};

function frame(ts: number) {
  requestAnimationFrame(frame);
  const dt = Math.min(0.1, (ts - last) / 1000); last = ts;
  const { state, transportLive } = client.step();
  const m = applyMapping(state, cfg.mapping);
  $('#conn').textContent = !transportLive ? 'BRIDGE OFFLINE' : !state?.controls ? (state?.status === 'paused' ? 'RADIO DATA PAUSED' : 'RADIO DISCONNECTED') : state.status === 'demo' ? 'DEMO' : 'LIVE';

  if (learning) {
    const res = learning.learner.update(state, ts);
    if (res) {
      if (learning.kind === 'axis') cfg.mapping[learning.target as AxisName] = axisFromLearn(res);
      else (cfg.mapping as any)[learning.target] = switchFromLearn(res);
      stopLearn(); refreshForm(); save();
    } else if (ts - learning.since > 20000) stopLearn();
  }
  const banner = $('#banner');
  if (!learning) {
    const needsC = transportLive && state?.controls && !state.channels;
    banner.hidden = !needsC;
    if (needsC) banner.textContent = 'Channel data missing: install the current radio script (run `sticklink radio-script`, copy it to /SCRIPTS/FUNCTIONS/ on the radio SD card) and restart the radio to learn CH5–CH16 switches.';
  }

  yawAngle += m.yaw * 2.2 * dt; spin += dt * 25;
  drawDrone(($('#drone') as HTMLCanvasElement).getContext('2d')!, 380, 280, { roll: m.roll, pitch: m.pitch, yaw: yawAngle, thr: m.throttle, spin });
  for (const a of AXIS_NAMES) {
    const v = a === 'throttle' ? m.throttle : m[a], bar = $(`[data-bar="${a}"]`);
    setMeter(bar.querySelector('.meter')!, v, a !== 'throttle'); bar.querySelector('em')!.textContent = (v * (a === 'throttle' ? 100 : 100)).toFixed(0) + '%';
    const raw = rawOf(state, cfg.mapping[a].src), row = $(`[data-axis="${a}"] .meter`);
    setMeter(row, raw === null ? 0 : norm(raw));
  }
  for (const k of ['arm', 'flip'] as const) {
    const active = m[k], lamp = $(k === 'arm' ? '#armLamp' : '#flipLamp');
    lamp.classList.toggle('on', active === true); lamp.classList.toggle('off', active === null);
    const s = cfg.mapping[k], raw = s ? rawOf(state, s.src) : null;
    setMeter($(`[data-sw="${k}"] .meter`), raw === null ? 0 : norm(raw));
  }
  for (let i = 1; i <= 16; i++) {
    const raw = rawOf(state, `ch:${i}`), bar = $(`[data-ch="${i}"]`);
    setMeter(bar.querySelector('.meter')!, raw === null ? 0 : norm(raw)); bar.querySelector('em')!.textContent = raw === null ? '—' : String(raw);
  }
}

load().then(() => { build(); client.start(); requestAnimationFrame(frame); });
