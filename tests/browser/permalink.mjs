// Drives the settings panels in headless Chrome to check the permanent-link behaviour. usage: node permalink.mjs BASE_URL
// Prints one JSON object of observations; the Python test asserts on it.
import { spawn } from 'node:child_process';
const base = process.argv[2];
const port = 9200 + Math.floor(Math.random() * 600);
const chrome = spawn(process.env.CHROME || 'google-chrome-stable', ['--headless=new', '--no-sandbox', '--disable-gpu', `--remote-debugging-port=${port}`,
  `--user-data-dir=${process.env.TMPDIR || '/tmp'}/sticklink-perma-${port}`, 'about:blank'], { stdio: 'ignore' });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const out = { errors: [] };
const settings = async () => (await fetch(base + '/api/v1/settings')).json();

async function page(url) {
  const target = await (await fetch(`http://127.0.0.1:${port}/json/new?` + encodeURIComponent(url), { method: 'PUT' })).json();
  const ws = new WebSocket(target.webSocketDebuggerUrl); await new Promise((r) => (ws.onopen = r));
  let id = 0; const pending = new Map();
  ws.onmessage = (m) => {
    const d = JSON.parse(m.data);
    if (d.id && pending.has(d.id)) { pending.get(d.id)(d); pending.delete(d.id); }
    if (d.method === 'Runtime.exceptionThrown') out.errors.push(d.params.exceptionDetails.exception?.description || d.params.exceptionDetails.text);
  };
  const send = (method, params = {}) => new Promise((r) => { const i = ++id; pending.set(i, r); ws.send(JSON.stringify({ id: i, method, params })); });
  await send('Runtime.enable'); await send('Emulation.setDeviceMetricsOverride', { width: 1000, height: 700, deviceScaleFactor: 1, mobile: false });
  const ev = async (expr) => (await send('Runtime.evaluate', { expression: expr, returnByValue: true, awaitPromise: true })).result.result.value;
  await sleep(2500);
  const root = 'document.querySelector("stick-fx, stick-hud").shadowRoot';
  return {
    ev, close: () => ws.close(),
    open: () => ev(`document.dispatchEvent(new MouseEvent('dblclick',{bubbles:true}))`),
    link: () => ev(`${root}.querySelector('[name=permalink]').value`),
    note: () => ev(`${root}.querySelector('.linknote').textContent`),
    href: () => ev('location.href'),
    get: (name) => ev(`(()=>{const e=${root}.querySelector('[name="${name}"]'); return e.type==='checkbox'?e.checked:e.value})()`),
    set: (name, value, evt = 'change') => ev(`(()=>{const e=${root}.querySelector('[name="${name}"]'); if(e.type==='checkbox'){e.checked=${JSON.stringify(value)}}else{e.value=${JSON.stringify(value)}}; e.dispatchEvent(new Event('${evt}',{bubbles:true}))})()`),
    status: () => ev(`${root}.querySelector('.status').textContent`),
    setupLinkStillThere: () => ev(`!!${root}.querySelector('a[href="/setup"]')`),
  };
}

try {
  for (let i = 0; i < 100; i++) { try { await fetch(`http://127.0.0.1:${port}/json/version`); break; } catch { await sleep(200); } }
  for (const [name, path, field, first, second, scope] of [['fx', '/fx', 'style', 'hacker', 'inferno', 'fx'], ['hud', '/hud', 'layout', 'row', 'column', 'hud']]) {
    const r = {};
    // 1. a plain URL: saves to the server, shows a link, and the address bar never changes
    await fetch(base + '/api/v1/settings', { method: 'DELETE' });
    const p1 = await page(base + path); const href0 = await p1.href();
    await p1.open(); await sleep(300);
    r.plainLink0 = await p1.link(); r.plainNote = await p1.note();
    await p1.set(field, first); await sleep(900);
    r.plainLink1 = await p1.link();
    await p1.set(field, second); await sleep(900);
    r.plainLink2 = await p1.link();
    r.addressBarUnchanged = (await p1.href()) === href0;
    r.hrefHasNoQuery = !href0.includes('?');
    r.savedOnServer = (await settings())[scope === 'fx' ? field : 'hud'];
    r.setupLinkStillThere = name === 'fx' ? await p1.setupLinkStillThere() : true;
    p1.close();
    // 2. a link page: reproduces its link, ignores what is saved, and writes nothing to the server
    const serverBefore = JSON.stringify(await settings());
    const p2 = await page(r.plainLink1); const href1 = await p2.href();
    await p2.open(); await sleep(300);
    r.pinnedField = await p2.get(field);               // must be `first`, although the server holds `second`
    r.pinnedLink = await p2.link(); r.pinnedNote = await p2.note();
    await p2.set(field, second); await sleep(900);
    r.pinnedLinkAfter = await p2.link(); r.pinnedStatus = await p2.status();
    r.pinnedAddressUnchanged = (await p2.href()) === href1;
    r.serverUntouched = JSON.stringify(await settings()) === serverBefore;
    p2.close();
    out[name] = r;
  }
  console.log(JSON.stringify(out));
} finally { chrome.kill(); }
