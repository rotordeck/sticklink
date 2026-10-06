// Loads a Sticklink page in headless Chrome and prints what a test needs as JSON: page errors, canvas size, how much is drawn.
// usage: node check.mjs URL WIDTH HEIGHT WAIT_MS
import { spawn } from 'node:child_process';
const [url, W, H, wait] = process.argv.slice(2);
const chromePath = process.env.CHROME || 'google-chrome-stable';
const port = 9300 + Math.floor(Math.random() * 600);
const chrome = spawn(chromePath, ['--headless=new', '--no-sandbox', '--disable-gpu', `--remote-debugging-port=${port}`,
  `--user-data-dir=${process.env.TMPDIR || '/tmp'}/sticklink-chrome-${port}`, 'about:blank'], { stdio: 'ignore' });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let target;
try {
  for (let i = 0; i < 100; i++) { try { await fetch(`http://127.0.0.1:${port}/json/version`); break; } catch { await sleep(200); } }
  target = await (await fetch(`http://127.0.0.1:${port}/json/new?` + encodeURIComponent(url), { method: 'PUT' })).json();
  const ws = new WebSocket(target.webSocketDebuggerUrl); await new Promise((r) => (ws.onopen = r));
  let id = 0; const pending = new Map(); const errors = [];
  ws.onmessage = (m) => {
    const d = JSON.parse(m.data);
    if (d.id && pending.has(d.id)) { pending.get(d.id)(d); pending.delete(d.id); }
    if (d.method === 'Runtime.exceptionThrown') errors.push(d.params.exceptionDetails.exception?.description || d.params.exceptionDetails.text);
  };
  const send = (method, params = {}) => new Promise((r) => { const i = ++id; pending.set(i, r); ws.send(JSON.stringify({ id: i, method, params })); });
  await send('Runtime.enable');
  await send('Emulation.setDeviceMetricsOverride', { width: +W, height: +H, deviceScaleFactor: 1, mobile: false });
  await sleep(+wait);
  const probe = `(() => {
    const host = document.querySelector('stick-hud') || document.querySelector('stick-fx');
    const c = host && host.shadowRoot.querySelector('canvas');
    if (!c) return { canvas: null };
    const d = c.getContext('2d').getImageData(0, 0, c.width, c.height).data; let lit = 0;
    for (let i = 3; i < d.length; i += 4) if (d[i] > 24) lit++;
    return { canvas: [c.width, c.height], litFraction: lit / (c.width * c.height) };
  })()`;
  const result = (await send('Runtime.evaluate', { expression: probe, returnByValue: true })).result.result.value;
  console.log(JSON.stringify({ ...result, errors }));
  ws.close();
} finally { chrome.kill(); }
