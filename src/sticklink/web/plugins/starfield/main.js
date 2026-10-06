// Starfield: throttle = speed, roll/pitch = steering, yaw = spin.
const stars = [];
const COUNT = 220;
function reset(s) { s.x = (Math.random() * 2 - 1); s.y = (Math.random() * 2 - 1); s.z = Math.random() * 0.9 + 0.1; }

Sticklink.visualizer({
  init() { for (let i = 0; i < COUNT; i++) { const s = {}; reset(s); stars.push(s); } },
  draw(ctx, w, h, f) {
    const cx = w / 2 + f.sticks.roll * w * 0.15, cy = h / 2 + f.sticks.pitch * h * 0.15;
    const speed = 0.15 + f.throttle * 1.6;
    const spin = f.sticks.yaw * 0.8 * f.dt;
    const cos = Math.cos(spin), sin = Math.sin(spin);
    ctx.lineCap = 'round';
    for (const s of stars) {
      const px = s.x / s.z, py = s.y / s.z;
      s.z -= speed * f.dt * 0.5;
      const nx = s.x * cos - s.y * sin; s.y = s.x * sin + s.y * cos; s.x = nx;
      if (s.z <= 0.02) { reset(s); s.z = 1; continue; }
      const qx = s.x / s.z, qy = s.y / s.z, scale = Math.min(w, h) * 0.5;
      const sx = cx + qx * scale, sy = cy + qy * scale;
      if (sx < -50 || sx > w + 50 || sy < -50 || sy > h + 50) { reset(s); s.z = 1; continue; }
      const glow = 1 - s.z;
      ctx.strokeStyle = `hsla(${190 + f.energy * 120}, 90%, ${60 + glow * 35}%, ${0.25 + glow * 0.75})`;
      ctx.lineWidth = 0.5 + glow * 2.5;
      ctx.beginPath(); ctx.moveTo(cx + px * scale, cy + py * scale); ctx.lineTo(sx, sy); ctx.stroke();
    }
    if (!f.live) { ctx.fillStyle = 'rgba(255,255,255,.5)'; ctx.font = '14px sans-serif'; ctx.fillText('waiting for the radio…', 12, h - 12); }
  },
});
