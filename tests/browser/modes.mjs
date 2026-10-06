// Drives the Modes page in headless Chrome like a user: add ranges, drag and keyboard-move handles, sort by buttons and by dragging,
// test-switch a scene, toggle the master switch. usage: node modes.mjs BASE_URL. Prints JSON observations for the Python test.
import { spawn } from 'node:child_process';
const base = process.argv[2];
const port = 9100 + Math.floor(Math.random() * 600);
const chrome = spawn(process.env.CHROME || 'google-chrome-stable', ['--headless=new', '--no-sandbox', '--disable-gpu', `--remote-debugging-port=${port}`,
  `--user-data-dir=${process.env.TMPDIR || '/tmp'}/sticklink-modes-${port}`, 'about:blank'], { stdio: 'ignore' });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const out = { errors: [] };
const modes = async () => (await (await fetch(base + '/api/v1/scene-modes')).json());
const order = async () => (await modes()).modes.map((m) => m.scene);
try {
  for (let i = 0; i < 100; i++) { try { await fetch(`http://127.0.0.1:${port}/json/version`); break; } catch { await sleep(200); } }
  const target = await (await fetch(`http://127.0.0.1:${port}/json/new?` + encodeURIComponent(base + '/modes'), { method: 'PUT' })).json();
  const ws = new WebSocket(target.webSocketDebuggerUrl); await new Promise((r) => (ws.onopen = r));
  let id = 0; const pending = new Map();
  ws.onmessage = (m) => {
    const d = JSON.parse(m.data);
    if (d.id && pending.has(d.id)) { pending.get(d.id)(d); pending.delete(d.id); }
    if (d.method === 'Runtime.exceptionThrown') out.errors.push(d.params.exceptionDetails.exception?.description || d.params.exceptionDetails.text);
  };
  const send = (method, params = {}) => new Promise((r) => { const i = ++id; pending.set(i, r); ws.send(JSON.stringify({ id: i, method, params })); });
  const ev = async (expr) => (await send('Runtime.evaluate', { expression: expr, returnByValue: true, awaitPromise: true })).result.result.value;
  await send('Runtime.enable'); await send('Emulation.setDeviceMetricsOverride', { width: 1100, height: 1400, deviceScaleFactor: 1, mobile: false });
  await sleep(3000);

  const cardRect = (scene, sel) => ev(`(()=>{const c=[...document.querySelectorAll('.card')].find(x=>x.querySelector('.name').firstChild.textContent.trim().toLowerCase()===${JSON.stringify(scene.toLowerCase())}); if(!c) return null; const e=${sel ? `c.querySelector(${JSON.stringify(sel)})` : 'c'}; if(!e) return null; const r=e.getBoundingClientRect(); return {x:r.left+r.width/2,y:r.top+r.height/2,left:r.left,top:r.top,width:r.width,height:r.height}})()`);
  const click = async (x, y) => { for (const type of ['mousePressed', 'mouseReleased']) await send('Input.dispatchMouseEvent', { type, x, y, button: 'left', clickCount: 1 }); };
  const drag = async (from, to) => {
    await send('Input.dispatchMouseEvent', { type: 'mousePressed', x: from.x, y: from.y, button: 'left', clickCount: 1 });
    for (let k = 1; k <= 8; k++) await send('Input.dispatchMouseEvent', { type: 'mouseMoved', x: from.x + ((to.x - from.x) * k) / 8, y: from.y + ((to.y - from.y) * k) / 8, button: 'left' });
    await send('Input.dispatchMouseEvent', { type: 'mouseReleased', x: to.x, y: to.y, button: 'left', clickCount: 1 });
  };

  out.cardsAtStart = await ev(`document.querySelectorAll('.card').length`);          // every scene, since no mode exists yet
  out.hideUnusedAtStart = await ev(`document.querySelector('#hideUnused').checked`);
  out.obsText = await ev(`document.querySelector('#obsText').textContent`);

  // 1. Add Range on Drone: a first range appears and is saved
  const add = await cardRect('Drone', '.btn.primary'); await click(add.x, add.y); await sleep(900);
  out.afterAdd = await modes();
  // 2. drag the minimum handle to 1300 us
  const track = await cardRect('Drone', '.track'), minH = await cardRect('Drone', '.handle');
  const x1300 = track.left + ((1300 - 900) / 1200) * track.width;
  await drag({ x: minH.x, y: minH.y }, { x: x1300, y: minH.y }); await sleep(900);
  out.afterDrag = (await modes()).modes[0].ranges[0];
  // 3. keyboard: focus the min handle and press ArrowRight (+25) and PageUp (+100)
  await ev(`[...document.querySelectorAll('.card')].find(x=>x.querySelector('.name').firstChild.textContent.trim()==='Drone').querySelector('.handle').focus()`);
  for (const key of ['ArrowRight', 'PageUp']) {
    await send('Input.dispatchKeyEvent', { type: 'keyDown', key, code: key, windowsVirtualKeyCode: key === 'ArrowRight' ? 39 : 33 });
    await send('Input.dispatchKeyEvent', { type: 'keyUp', key, code: key });
  }
  await sleep(900);
  out.afterKeys = (await modes()).modes[0].ranges[0];
  // 4. the handle cannot be dragged past the other one
  const minH2 = await cardRect('Drone', '.handle'), track2 = await cardRect('Drone', '.track');
  await drag({ x: minH2.x, y: minH2.y }, { x: track2.left + track2.width * 0.99, y: minH2.y }); await sleep(900);
  out.afterOvershoot = (await modes()).modes[0].ranges[0];
  // 5. a live marker is drawn for the AUX channel the demo radio drives
  out.markerVisible = await ev(`!!document.querySelector('.marker') && !document.querySelector('.marker').hidden`);
  // 6. two more scenes become modes; sort with the buttons, then by dragging
  for (const scene of ['Room', 'Instant replay']) { const b = await cardRect(scene, '.btn.primary'); await click(b.x, b.y); await sleep(700); }
  out.orderAfterAdds = await order();                                                    // Drone, Room, Instant replay
  const up = await cardRect('Instant replay', '.prio .btn.tiny'); await click(up.x, up.y); await sleep(900);
  out.orderAfterUpButton = await order();                                                // Drone, Instant replay, Room
  const grip = await cardRect('Room', '.grip'), top = await cardRect('Drone');
  await drag({ x: grip.x, y: grip.y }, { x: grip.x, y: top.top + 10 }); await sleep(900);
  out.orderAfterDrag = await order();                                                    // Room, Drone, Instant replay
  out.priorityLabels = await ev(`[...document.querySelectorAll('.card .prio .num')].map(n=>n.textContent)`);
  // 7. test-switch: "Show in OBS"
  const show = await cardRect('Drone', '.btn.small:not(.primary)'); await click(show.x, show.y); await sleep(600);
  out.status = await ev(`document.querySelector('#status').textContent`);
  // 8. master switch on, then off again (never leave the engine enabled)
  await click(...(await ev(`(()=>{const r=document.querySelector('#enabled').getBoundingClientRect(); return [r.left+r.width/2, r.top+r.height/2]})()`))); await sleep(900);
  out.enabledOn = (await modes()).enabled;
  await click(...(await ev(`(()=>{const r=document.querySelector('#enabled').getBoundingClientRect(); return [r.left+r.width/2, r.top+r.height/2]})()`))); await sleep(900);
  out.enabledOff = (await modes()).enabled;
  // 9. removing the last range un-uses the scene
  const del = await cardRect('Instant replay', '.btn.x'); await click(del.x, del.y); await sleep(900);
  out.orderAfterRemove = await order();
  out.finalCards = await ev(`document.querySelectorAll('.card').length`);
  console.log(JSON.stringify(out));
  ws.close();
} finally { chrome.kill(); }
