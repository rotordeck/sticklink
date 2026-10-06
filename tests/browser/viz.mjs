// Opens visualiser plugins in headless Chrome and reports what the host page saw. usage: node viz.mjs BASE_URL id1 id2 ...
import { spawn } from 'node:child_process';
const [base, ...ids] = process.argv.slice(2);
const port = 9100 + Math.floor(Math.random() * 600);
const chrome = spawn(process.env.CHROME || 'google-chrome-stable', ['--headless=new', '--no-sandbox', '--disable-gpu', `--remote-debugging-port=${port}`,
  `--user-data-dir=${process.env.TMPDIR || '/tmp'}/sticklink-viz-${port}`, 'about:blank'], { stdio: 'ignore' });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const out = {};
try {
  for (let i = 0; i < 100; i++) { try { await fetch(`http://127.0.0.1:${port}/json/version`); break; } catch { await sleep(200); } }
  for (const id of [...ids, 'gallery']) {
    const url = id === 'gallery' ? base + '/viz' : `${base}/viz/${id}`;
    const target = await (await fetch(`http://127.0.0.1:${port}/json/new?` + encodeURIComponent(url), { method: 'PUT' })).json();
    const ws = new WebSocket(target.webSocketDebuggerUrl); await new Promise((r) => (ws.onopen = r));
    let n = 0; const pending = new Map(); const errors = [];
    ws.onmessage = (m) => {
      const d = JSON.parse(m.data);
      if (d.id && pending.has(d.id)) { pending.get(d.id)(d); pending.delete(d.id); }
      if (d.method === 'Runtime.exceptionThrown') errors.push(d.params.exceptionDetails.exception?.description || d.params.exceptionDetails.text);
    };
    const send = (method, params = {}) => new Promise((r) => { const i = ++n; pending.set(i, r); ws.send(JSON.stringify({ id: i, method, params })); });
    await send('Runtime.enable'); await send('Emulation.setDeviceMetricsOverride', { width: 800, height: 450, deviceScaleFactor: 1, mobile: false });
    await sleep(4500);
    const read = async (expr) => (await send('Runtime.evaluate', { expression: expr, returnByValue: true, awaitPromise: true })).result.result.value;
    out[id] = id === 'gallery'
      ? { cards: await read(`document.querySelectorAll('.card').length`), names: await read(`[...document.querySelectorAll('.name')].map(e=>e.textContent)`),
          frames: await read(`document.querySelectorAll('iframe').length`), errors }
      : { data: await read(`({...document.body.dataset})`), banner: await read(`getComputedStyle(document.getElementById('msg')).display`), errors };
    if (process.env.SHOTS) {
      const shot = await send('Page.captureScreenshot', { format: 'png' });
      (await import('node:fs')).writeFileSync(`${process.env.SHOTS}/viz-${id}.png`, Buffer.from(shot.result.data, 'base64'));
    }
    ws.close();
  }
  console.log(JSON.stringify(out));
} finally { chrome.kill(); }
process.exit(0);
