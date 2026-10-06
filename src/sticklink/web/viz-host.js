// The trusted page around a plugin: it holds the WebSocket and hands each state to the sandboxed frame.
import { StickLinkClient } from '/assets/client.js';

const id = decodeURIComponent(location.pathname.split('/')[2] || '');
const msg = document.getElementById('msg');
const frame = document.createElement('iframe');
frame.setAttribute('sandbox', 'allow-scripts');  // no same-origin: the plugin cannot reach this page, the API, or storage
frame.src = `/viz/${encodeURIComponent(id)}/frame`;
document.body.prepend(frame);

const client = new StickLinkClient(0);
client.start();
let sent = null;
const info = { id };
function pump() {
  requestAnimationFrame(pump);
  const state = client.latest;
  if (state && state !== sent && frame.contentWindow) {
    sent = state;
    frame.contentWindow.postMessage({ sticklink: 'state', state, info }, '*');
  }
}
pump();
setInterval(() => { if (frame.contentWindow && client.latest) frame.contentWindow.postMessage({ sticklink: 'state', state: client.latest, info }, '*'); }, 500);  // keeps a late-loading plugin fed

addEventListener('message', (event) => {
  if (event.source !== frame.contentWindow || !event.data || event.data.sticklink !== 'viz') return;
  const d = event.data;
  if (d.type === 'error') { msg.textContent = `Plugin "${id}" failed: ${d.text}`; msg.style.display = 'block'; document.body.dataset.error = d.text; }
  else if (d.type === 'log') { console.log(`[${id}]`, d.text); document.body.dataset.log = d.text; }
  else if (d.type === 'frames') document.body.dataset.frames = String(d.frames);
  else if (d.type === 'ready') document.body.dataset.ready = d.plugin ? 'plugin' : 'no-plugin';
});
