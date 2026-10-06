// Optional DOM check: JSDOM_PATH=<path to jsdom> node tests/test_components.cjs
const fs = require('fs'), path = require('path'), assert = require('assert');
const {JSDOM} = require(process.env.JSDOM_PATH || 'jsdom');
const web = path.join(__dirname,'../src/sticklink/web');
// Concatenate the ES modules into one script: drop imports, strip exports.
const source = ['client.js','components.js'].map(f=>fs.readFileSync(path.join(web,f),'utf8')).join('\n')
  .replace(/^import .*$/gm,'').replace(/^export /gm,'');
function setup(query='') {
  const dom = new JSDOM('<body></body>',{url:'http://127.0.0.1:8765/overlay'+query,runScripts:'outside-only'});
  const w=dom.window; let now=0; w.performance.now=()=>now;
  w.setInterval=()=>1; w.clearInterval=()=>{}; w.setTimeout=()=>1; w.clearTimeout=()=>{};
  class FakeWS {
    static OPEN=1;
    constructor(url) { this.url=url; this.readyState=1; }
    close() { this.readyState=3; this.onclose?.(); }
  }
  w.WebSocket=FakeWS; w.eval(source);
  const overlay=w.document.createElement('drone-stick-overlay'); w.document.body.append(overlay);
  return {dom,overlay,advance:n=>{now=n;},feed:s=>overlay.socket.onmessage({data:JSON.stringify(s)})};
}
const frame={schema:1,session:1,status:'live',source:'sticks',controls:{roll:1,pitch:-.5,yaw:.5,throttle:-1},commands:{arm:true,crash:false},telemetry:{RQly:{value:99,current:true},RxBt:{value:4.08,current:true}},seq:1,tick:100,age_ms:0,diagnostics:{missing:0,invalid:0}};
const a=setup(); a.feed(frame); a.overlay.render();
const root=a.overlay.shadowRoot, sticks=[...root.querySelectorAll('fpv-stick')];
assert.equal(sticks[0].shadowRoot.querySelector('.dot').getAttribute('cx'),'161.50');
assert.equal(sticks[0].shadowRoot.querySelector('.dot').getAttribute('cy'),'199.00');
assert.equal(sticks[1].shadowRoot.querySelector('.dot').getAttribute('cx'),'204.00');
assert.equal(root.querySelector('.status').textContent,'LIVE · STICKS');
assert(root.querySelector('fpv-command').hasAttribute('on'));
assert.deepEqual([...root.querySelectorAll('.telemetry span')].map(e=>e.textContent),['LQ 99%','BAT 4.08V']);
a.feed({...frame,seq:2,status:'paused',controls:null,commands:{arm:null,crash:null}}); a.overlay.render();
assert(sticks[0].hasAttribute('stale')); assert.equal(root.querySelector('.status').textContent,'RADIO DATA PAUSED');
a.overlay.socket.close(); a.overlay.render(); assert.equal(root.querySelector('.status').textContent,'BRIDGE OFFLINE');
const b=setup('?mode=1&minimal=1&telemetry=0&delay=120&invert=pitch&color=ffaa66');
b.feed(frame); b.overlay.render(); assert.equal(b.overlay.shadowRoot.querySelector('.status').textContent,'BUFFERING');
b.advance(130); b.overlay.render(); const br=b.overlay.shadowRoot;
assert.equal(br.querySelector('fpv-stick').shadowRoot.querySelector('.label').textContent,'YAW / PITCH');
assert.equal(br.querySelector('fpv-stick').shadowRoot.querySelector('.dot').getAttribute('cy'),'71.50');
assert(b.overlay.hasAttribute('minimal')); assert(br.querySelector('.telemetry').hidden);
assert.equal(b.overlay.style.getPropertyValue('--accent'),'#ffaa66');
b.advance(1200); b.overlay.render(); assert.equal(br.querySelector('.status').textContent,'BRIDGE OFFLINE');
const c=setup('?sensors=RxBt:CELL:V,Foo:X:dB,bad name:Z');
c.feed({...frame,telemetry:{...frame.telemetry,Foo:{value:12.6,current:true}}}); c.overlay.render();
const texts=[...c.overlay.shadowRoot.querySelectorAll('.telemetry span')].map(e=>e.textContent);
assert.deepEqual(texts,['CELL 4.08V','X 13dB']);
a.dom.window.close(); b.dom.window.close(); c.dom.window.close();
console.log('PASS DOM: custom elements, axis coordinates, ARM, telemetry, stale/offline, mode, invert, delay, minimal, color, sensors');

// trail is a smooth Bezier path through the readings (not a polyline with corners)
{
  const t = setup(); t.feed(frame); t.overlay.render();
  const stick = t.overlay.shadowRoot.querySelector('fpv-stick').shadowRoot;
  assert.equal(stick.querySelector('polyline'), null);
  for (let k = 1; k <= 5; k++) { t.feed({...frame, seq: 10 + k, controls: {roll: Math.sin(k), pitch: Math.cos(k), yaw: k / 6, throttle: 0}}); t.overlay.render(); }
  const d = stick.querySelector('.trail').getAttribute('d');
  assert(d.startsWith('M') && (d.match(/ C/g) || []).length >= 4, d);
  assert(!/NaN/.test(d));
  t.dom.window.close();
  console.log('PASS DOM: trail is a smooth path');
}
