// Runs inside the sandboxed frame. A plugin calls Sticklink.visualizer({...}); this file owns the canvas, the animation
// loop, smoothing and history, and receives live data from the page that hosts the frame (the frame itself has no network).
(function () {
  'use strict';
  const canvas = document.getElementById('c');
  const ctx = canvas.getContext('2d');
  const KEYS = ['roll', 'pitch', 'yaw', 'throttle'];
  const HISTORY_S = 10;
  let def = null, info = {}, latest = null, failed = false, started = performance.now() / 1000, last = started;
  let frames = 0, width = 0, height = 0, dpr = 1;
  const smooth = { roll: 0, pitch: 0, yaw: 0, throttle: -1 };
  const history = [];  // {t, roll, pitch, yaw, throttle}, newest last
  let energy = 0;

  const post = (message) => { try { parent.postMessage(Object.assign({ sticklink: 'viz' }, message), '*'); } catch (_) { /* no parent */ } };

  window.Sticklink = {
    api: 1,
    visualizer(definition) {
      if (typeof definition !== 'object' || typeof definition.draw !== 'function') throw new Error('Sticklink.visualizer needs an object with a draw(ctx, w, h, f) function');
      def = definition;
    },
    log(...parts) { post({ type: 'log', text: parts.map(String).join(' ').slice(0, 300) }); },
  };

  addEventListener('message', (event) => {
    if (event.source !== parent || !event.data || event.data.sticklink !== 'state') return;
    if (event.data.info) info = event.data.info;
    latest = event.data.state;
  });

  function resize() {
    dpr = Math.min(2, window.devicePixelRatio || 1);
    const w = Math.max(1, Math.round(innerWidth)), h = Math.max(1, Math.round(innerHeight));
    if (w !== width || h !== height || canvas.width !== Math.round(w * dpr)) {
      width = w; height = h;
      canvas.width = Math.round(w * dpr); canvas.height = Math.round(h * dpr);
      if (def && def.resize) guarded(() => def.resize(ctx, width, height));
    }
  }

  function guarded(fn) {
    try { return fn(); } catch (error) {
      failed = true;
      post({ type: 'error', text: String(error && error.message || error).slice(0, 300) });
      console.error(error);
    }
  }

  function frame(now) {
    requestAnimationFrame(frame);
    if (!def || failed) return;
    const t = now / 1000, dt = Math.min(0.1, Math.max(0.001, t - last)); last = t;
    const s = latest, live = !!s && (s.status === 'live' || s.status === 'demo') && !!s.controls;
    const controls = live ? s.controls : { roll: 0, pitch: 0, yaw: 0, throttle: -1 };
    const k = 1 - Math.exp(-dt / 0.04);  // ~40 ms: hides the 20 Hz steps without a visible lag
    let moved = 0;
    for (const key of KEYS) {
      const before = smooth[key];
      smooth[key] += (controls[key] - smooth[key]) * k;
      moved += Math.abs(smooth[key] - before);
    }
    energy += (Math.min(1, moved / dt / 4) - energy) * (1 - Math.exp(-dt / 0.25));
    history.push({ t, roll: smooth.roll, pitch: smooth.pitch, yaw: smooth.yaw, throttle: smooth.throttle });
    while (history.length && history[0].t < t - HISTORY_S) history.shift();

    resize();
    const f = {
      t: t - started, dt, live, status: s ? s.status : 'disconnected',
      sticks: Object.assign({}, smooth), raw: live ? Object.assign({}, controls) : null,
      throttle: (smooth.throttle + 1) / 2,  // 0..1
      energy,  // 0..1, how busy the sticks are right now
      armed: s && s.commands ? s.commands.arm : null, crash: s && s.commands ? s.commands.crash : null,
      channels: s && s.channels ? s.channels.map((v) => Math.max(-1, Math.min(1, v / 1024))) : null,
      telemetry: s ? Object.fromEntries(Object.entries(s.telemetry || {}).map(([name, v]) => [name, v.current ? v.value : null])) : {},
      gps: s ? s.gps : null,
      trail(seconds) { const from = t - Math.min(HISTORY_S, seconds); return history.filter((h) => h.t >= from).map((h) => ({ age: t - h.t, roll: h.roll, pitch: h.pitch, yaw: h.yaw, throttle: h.throttle })); },
    };
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    guarded(() => {
      if (frames === 0 && def.init) def.init(ctx, width, height, info);
      ctx.clearRect(0, 0, width, height);
      ctx.save();
      def.draw(ctx, width, height, f);
      ctx.restore();
    });
    if (failed) {
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.fillStyle = 'rgba(0,0,0,.7)'; ctx.fillRect(0, 0, width, 28);
      ctx.fillStyle = '#ff6b6b'; ctx.font = '13px sans-serif'; ctx.fillText('Plugin error: see the message below / browser console', 10, 18);
    }
    if (++frames % 30 === 0) post({ type: 'frames', frames });
  }
  addEventListener('load', () => { post({ type: 'ready', plugin: !!def }); requestAnimationFrame(frame); });
})();
