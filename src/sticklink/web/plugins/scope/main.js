// Phosphor scope: the right-stick style X/Y trace (roll/pitch) over the last 3 seconds, plus a throttle bar.
Sticklink.visualizer({
  draw(ctx, w, h, f) {
    const size = Math.min(w, h) * 0.86, cx = w / 2, cy = h / 2, half = size / 2;
    ctx.strokeStyle = 'rgba(80,255,150,.18)'; ctx.lineWidth = 1;
    ctx.strokeRect(cx - half, cy - half, size, size);
    for (let i = 1; i < 4; i++) {
      const o = (size / 4) * i;
      ctx.beginPath(); ctx.moveTo(cx - half + o, cy - half); ctx.lineTo(cx - half + o, cy + half);
      ctx.moveTo(cx - half, cy - half + o); ctx.lineTo(cx + half, cy - half + o); ctx.stroke();
    }
    const trail = f.trail(3);
    ctx.lineCap = 'round'; ctx.shadowColor = '#3dff9a'; ctx.shadowBlur = 14;
    for (let i = 1; i < trail.length; i++) {
      const a = trail[i - 1], b = trail[i], fade = 1 - b.age / 3;
      ctx.strokeStyle = `rgba(80,255,150,${Math.max(0, fade)})`; ctx.lineWidth = 1 + fade * 3;
      ctx.beginPath(); ctx.moveTo(cx + a.roll * half, cy + a.pitch * half); ctx.lineTo(cx + b.roll * half, cy + b.pitch * half); ctx.stroke();
    }
    const x = cx + f.sticks.roll * half, y = cy + f.sticks.pitch * half;
    ctx.fillStyle = '#eafff3'; ctx.beginPath(); ctx.arc(x, y, 5 + f.energy * 4, 0, Math.PI * 2); ctx.fill();
    ctx.shadowBlur = 0;
    const bx = cx + half + 16, bh = size;
    if (bx + 14 < w) {
      ctx.strokeStyle = 'rgba(80,255,150,.4)'; ctx.strokeRect(bx, cy - half, 12, bh);
      ctx.fillStyle = '#3dff9a'; ctx.fillRect(bx, cy + half - bh * f.throttle, 12, bh * f.throttle);
    }
  },
});
