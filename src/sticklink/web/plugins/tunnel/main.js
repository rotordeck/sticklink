// Neon tunnel: rings travel towards the viewer; sticks bend and twist them.
let phase = 0, twist = 0;

Sticklink.visualizer({
  draw(ctx, w, h, f) {
    phase = (phase + (0.15 + f.throttle * 1.2) * f.dt) % 1;
    twist += f.sticks.yaw * 1.5 * f.dt;
    const rings = 16, size = Math.min(w, h) * 0.5;
    ctx.globalCompositeOperation = 'lighter';
    ctx.lineJoin = 'round';
    for (let i = rings; i >= 0; i--) {
      const d = (i + phase) / rings;               // 0 = far, 1 = near
      const k = d * d;
      const x = w / 2 + f.sticks.roll * (1 - d) * w * 0.35, y = h / 2 + f.sticks.pitch * (1 - d) * h * 0.35;
      const r = k * size * 1.4 + 2, sides = 6, rot = twist * (1 - d) + d;
      ctx.beginPath();
      for (let s = 0; s <= sides; s++) {
        const a = rot + (s / sides) * Math.PI * 2;
        ctx[s ? 'lineTo' : 'moveTo'](x + Math.cos(a) * r, y + Math.sin(a) * r);
      }
      ctx.strokeStyle = `hsla(${280 - d * 100 + f.energy * 60}, 100%, 60%, ${0.15 + d * 0.8})`;
      ctx.lineWidth = 1 + d * 5;
      ctx.shadowColor = ctx.strokeStyle; ctx.shadowBlur = 12 * d;
      ctx.stroke();
    }
  },
});
