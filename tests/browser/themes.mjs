// Opens /fx and /hud in headless Chrome and reports which style they ended up with. usage: node themes.mjs BASE_URL
import { spawn } from 'node:child_process';
const base = process.argv[2];
const port = 9100 + Math.floor(Math.random() * 600);
const chrome = spawn(process.env.CHROME || 'google-chrome-stable', ['--headless=new', '--no-sandbox', '--disable-gpu', `--remote-debugging-port=${port}`,
  `--user-data-dir=${process.env.TMPDIR || '/tmp'}/sticklink-themes-${port}`, 'about:blank'], { stdio: 'ignore' });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const out = {};
try {
  for (let i = 0; i < 100; i++) { try { await fetch(`http://127.0.0.1:${port}/json/version`); break; } catch { await sleep(200); } }
  for (const [key, path, expr] of [
    ['fx', '/fx', `(() => { const e = document.querySelector('stick-fx'); e.syncPanel(); return { ring: e.scene.style.ring, dot: e.scene.style.dot, glow: e.scene.style.glow, trail: e.scene.style.trail,
        options: [...e.shadowRoot.querySelectorAll('select[name=style] option')].map(o => o.textContent), selected: e.shadowRoot.querySelector('select[name=style]').value, cfgStyle: e.cfg.style }; })()`],
    ['hud', '/hud', `(() => { const e = document.querySelector('stick-hud'); return { cfgStyle: e.cfg.style, hudStyle: e.cfg.hud.style }; })()`],
    ['missing', '/fx?style=gone', `(() => { const e = document.querySelector('stick-fx'); return { cfgStyle: e.cfg.style }; })()`],
  ]) {
    const target = await (await fetch(`http://127.0.0.1:${port}/json/new?` + encodeURIComponent(base + path), { method: 'PUT' })).json();
    const ws = new WebSocket(target.webSocketDebuggerUrl); await new Promise((r) => (ws.onopen = r));
    let n = 0; const pending = new Map(); const errors = [];
    ws.onmessage = (m) => {
      const d = JSON.parse(m.data);
      if (d.id && pending.has(d.id)) { pending.get(d.id)(d); pending.delete(d.id); }
      if (d.method === 'Runtime.exceptionThrown') errors.push(d.params.exceptionDetails.exception?.description || d.params.exceptionDetails.text);
    };
    const send = (method, params = {}) => new Promise((r) => { const i = ++n; pending.set(i, r); ws.send(JSON.stringify({ id: i, method, params })); });
    await send('Runtime.enable'); await send('Emulation.setDeviceMetricsOverride', { width: 800, height: 600, deviceScaleFactor: 1, mobile: false });
    await sleep(3000);
    out[key] = { ...(await send('Runtime.evaluate', { expression: expr, returnByValue: true })).result.result.value, errors };
    ws.close();
  }
  console.log(JSON.stringify(out));
} finally { chrome.kill(); }
process.exit(0);
