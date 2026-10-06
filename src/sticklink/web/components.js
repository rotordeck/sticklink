// Native custom elements: reusable in OBS and in other local web views.
import {StickLinkClient} from './client.js';
const params = new URLSearchParams(location.search);
const finiteParam = (key, fallback, min, max) => {
  if (!params.has(key)) return fallback;
  const n = Number(params.get(key));
  return Number.isFinite(n) ? Math.max(min, Math.min(max, n)) : fallback;
};
const delayMs = finiteParam('delay', 0, 0, 5000);
const mode = Math.round(finiteParam('mode', 2, 1, 4));
const inverted = new Set((params.get('invert') || '').split(','));
const showTelemetry = params.get('telemetry') !== '0';
const showTrail = params.get('trail') !== '0';
// ?sensors=name:label:unit,... (unit V = two decimals)
const sensorSpecs = (params.get('sensors') || 'RQly:LQ:%,RxBt:BAT:V').split(',')
  .map(s => s.split(':')).filter(a => /^[A-Za-z0-9_-]{1,24}$/.test(a[0]))
  .map(([name, label = name, unit = '']) => ({name, label: label.slice(0, 8), unit: unit.slice(0, 4)}));

// Smooth path through the readings (Catmull-Rom as cubic Beziers): fluid curve, passes through every real point.
export function smoothPath(pts) {
  if (!pts.length) return '';
  const f = n => n.toFixed(1);
  let d = `M${f(pts[0][0])},${f(pts[0][1])}`;
  if (pts.length === 1) return d + ` L${f(pts[0][0])},${f(pts[0][1])}`; // a lone point still shows as a dot
  for (let i = 0; i < pts.length - 1; i++) {
    const p0 = pts[Math.max(0, i - 1)], p1 = pts[i], p2 = pts[i + 1], p3 = pts[Math.min(pts.length - 1, i + 2)];
    d += ` C${f(p1[0] + (p2[0] - p0[0]) / 6)},${f(p1[1] + (p2[1] - p0[1]) / 6)}` +
         ` ${f(p2[0] - (p3[0] - p1[0]) / 6)},${f(p2[1] - (p3[1] - p1[1]) / 6)} ${f(p2[0])},${f(p2[1])}`;
  }
  return d;
}

export class FpvStick extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({mode:'open'});
    this.shadowRoot.innerHTML = `
      <style>
        :host{display:block;width:238px}svg{display:block;width:100%;overflow:visible}
        .base{fill:#0b1420;fill-opacity:.83;stroke:#788b9e;stroke-width:1.2}
        .grid{stroke:#b7c9db;stroke-opacity:.22;stroke-width:1}
        .ring{fill:none;stroke:#b7c9db;stroke-opacity:.12}
        .trail{fill:none;stroke:var(--accent,#50e0c1);stroke-width:2.5;stroke-linecap:round;stroke-linejoin:round;opacity:.45}
        .dot{fill:var(--accent,#50e0c1);stroke:#fff;stroke-width:2}
        text{fill:#dce9f6;font:11px Arial,sans-serif;text-anchor:middle;letter-spacing:1.3px}
        .values{font-size:10px;letter-spacing:0;fill:#a3b3c3}
        :host([stale]) .dot,:host([stale]) .trail{display:none}
      </style>
      <svg viewBox="0 0 238 254" aria-label="stick position">
        <rect class="base" x="20" y="15" width="198" height="198" rx="26"/>
        <circle class="ring" cx="119" cy="114" r="80"/>
        <path class="grid" d="M119 24V204 M29 114H209"/>
        <path class="grid" d="M75 110V118 M163 110V118 M115 70H123 M115 158H123"/>
        <path class="trail"/>
        <circle class="dot" cx="119" cy="114" r="8"/>
        <text class="label" x="119" y="234"></text>
        <text class="values" x="119" y="251"></text>
      </svg>`;
    this.dot = this.shadowRoot.querySelector('.dot');
    this.trail = this.shadowRoot.querySelector('.trail');
    this.values = this.shadowRoot.querySelector('.values');
    this.points = [];
  }
  setLabel(label) { this.shadowRoot.querySelector('.label').textContent = label; }
  update(x, y, live) {
    this.toggleAttribute('stale', !live);
    if (!live) { this.points = []; this.trail.setAttribute('d',''); this.values.textContent='—'; return; }
    const cx = 119 + x * 85, cy = 114 - y * 85;
    this.dot.setAttribute('cx',cx.toFixed(2)); this.dot.setAttribute('cy',cy.toFixed(2));
    this.values.textContent = `${Math.round(x*100)}%  /  ${Math.round(y*100)}%`;
    if (showTrail) {
      this.points.push([cx,cy]);
      if (this.points.length > 16) this.points.shift();
      this.trail.setAttribute('d',smoothPath(this.points));
    }
  }
}
customElements.define('fpv-stick', FpvStick);

export class FpvCommand extends HTMLElement {
  constructor() {
    super(); this.attachShadow({mode:'open'});
    this.shadowRoot.innerHTML = `<style>
      :host{display:inline-flex;border:1px solid #556575;border-radius:6px;padding:7px 10px;font:10px Arial,sans-serif;letter-spacing:.8px;color:#adbac8;background:#0b1420cc}
      :host([on]){color:#ffb875;border-color:#d98441;background:#33200fd9}
      :host([unknown]){opacity:.4}
    </style><span></span>`;
  }
  update(label,value) {
    this.toggleAttribute('on',value === true);
    this.toggleAttribute('unknown',value == null);
    this.shadowRoot.querySelector('span').textContent = `${label} ${value == null ? '—' : value ? 'ON' : 'OFF'}`;
  }
}
customElements.define('fpv-command', FpvCommand);

const modeAxes = {
  1: [['yaw','pitch'], ['roll','throttle']],
  2: [['yaw','throttle'], ['roll','pitch']],
  3: [['roll','pitch'], ['yaw','throttle']],
  4: [['roll','throttle'], ['yaw','pitch']],
};
const axisLabels = {yaw:'YAW',throttle:'THROTTLE',roll:'ROLL',pitch:'PITCH'};

export class DroneStickOverlay extends HTMLElement {
  constructor() {
    super(); this.attachShadow({mode:'open'});
    this.shadowRoot.innerHTML = `<style>
      :host{display:block;--accent:#50e0c1}
      .wrap{box-sizing:border-box;width:560px;padding:16px 16px 12px;border-radius:22px;background:linear-gradient(145deg,#111d2aec,#09111cd9);border:1px solid #7d94ac44;box-shadow:0 4px 24px #0003}
      .head,.footer,.telemetry{display:flex;align-items:center;justify-content:space-between;gap:10px}
      .brand{font-size:13px;font-weight:700;letter-spacing:2px}
      .meta{font-size:10px;letter-spacing:1px;color:#9aafc1}.status{font-size:10px;letter-spacing:1px;color:var(--accent)}
      .sticks{display:flex;justify-content:space-between;margin-top:12px}
      .footer{margin-top:14px}.commands{display:flex;gap:7px}
      .telemetry{font-size:11px;color:#b4c4d3;justify-content:flex-end}.muted{opacity:.38}
      .diag{margin-top:10px;font-size:10px;color:#a4b4c7;display:none}[hidden]{display:none}
      :host([lost]) .status{color:#ffb875}
      :host([minimal]) .wrap{background:none;border:0;box-shadow:none}
      :host([minimal]) .head,:host([minimal]) .footer{display:none}
    </style>
    <div class="wrap">
      <div class="head"><div><span class="brand">STICKLINK</span><span class="meta"> · MODE ${mode}</span></div><span class="status">CONNECTING</span></div>
      <div class="sticks"><fpv-stick></fpv-stick><fpv-stick></fpv-stick></div>
      <div class="footer"><div class="commands"><fpv-command></fpv-command><fpv-command></fpv-command></div>
        <div class="telemetry"></div></div>
      <div class="diag"></div>
    </div>`;
    this.sticks = [...this.shadowRoot.querySelectorAll('fpv-stick')];
    this.commands = [...this.shadowRoot.querySelectorAll('fpv-command')];
    this.axes = modeAxes[mode] || modeAxes[2];
    this.axes.forEach((a,i)=>this.sticks[i].setLabel(a.map(k=>axisLabels[k]).join(' / ')));
    this.client = new StickLinkClient(delayMs); this.lastRendered = null;
    this.sensorEls = sensorSpecs.map(spec => {
      const el = document.createElement('span'); el.textContent = `${spec.label} —`;
      this.shadowRoot.querySelector('.telemetry').append(el); return [spec, el];
    });
    this.shadowRoot.querySelector('.telemetry').hidden = !showTelemetry;
    if (params.get('debug') === '1') this.shadowRoot.querySelector('.diag').style.display='block';
  }
  connectedCallback() {
    // A custom element constructor must not add attributes to its own host.
    this.toggleAttribute('minimal',params.get('minimal') === '1');
    if (/^#[0-9a-f]{6}$/i.test('#'+params.get('color'))) this.style.setProperty('--accent','#'+params.get('color'));
    this.client.start();
    this.timer = setInterval(()=>this.render(), 1000/60);
  }
  disconnectedCallback() { clearInterval(this.timer); this.client.stop(); }
  get socket() { return this.client.socket; }
  render() {
    const {state, transportLive} = this.client.step();
    // Honour delayed radio status; transport failures are shown immediately.
    const live = transportLive && !!state?.controls && ['live','demo'].includes(state.status);
    this.toggleAttribute('lost',!live);
    const status = this.shadowRoot.querySelector('.status');
    const source = state?.source === 'sticks' ? 'STICKS' : state?.source === 'outputs' ? 'OUTPUTS' : 'INPUT';
    status.textContent = !transportLive ? 'BRIDGE OFFLINE' : !state ? 'BUFFERING' :
      live ? `${state.status === 'demo' ? 'DEMO' : 'LIVE'} · ${source}` :
      state.status === 'paused' ? 'RADIO DATA PAUSED' : 'RADIO DISCONNECTED';
    const frameKey = state ? `${state.session}:${state.seq}:${live}` : `offline:${live}`;
    if (frameKey !== this.lastRendered) {
      this.lastRendered = frameKey;
      const value = k => (state?.controls?.[k] || 0) * (inverted.has(k) ? -1 : 1);
      this.axes.forEach((a,i)=>this.sticks[i].update(value(a[0]),value(a[1]),live));
    }
    this.commands[0].update('ARM CMD',live ? state.commands.arm : null);
    this.commands[1].update('FLIP CMD',live ? state.commands.crash : null);
    const sensors = state?.telemetry || {};
    for (const [spec, el] of this.sensorEls) {
      const sensor = sensors[spec.name], valid = transportLive && sensor?.current;
      el.classList.toggle('muted', !valid);
      const v = valid ? (spec.unit === 'V' ? Number(sensor.value).toFixed(2) : Math.round(sensor.value)) : '';
      el.textContent = valid ? `${spec.label} ${v}${spec.unit}` : `${spec.label} —`;
    }
    const d = state?.diagnostics;
    this.shadowRoot.querySelector('.diag').textContent = d ?
      `tick ${state.tick} · seq ${state.seq} · age ${state.age_ms ?? '—'}ms · missing ${d.missing} · invalid ${d.invalid} · delay ${delayMs}ms` : 'Waiting for Python bridge';
  }
}
customElements.define('drone-stick-overlay',DroneStickOverlay);
