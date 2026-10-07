// A tiny wireframe quad on a canvas, tilted by the sticks (like Betaflight Configurator's receiver tab).
export interface Pose { roll: number; pitch: number; yaw: number; thr: number; spin: number } // roll/pitch -1..1, yaw rad, thr 0..1, spin rad

type V = [number, number, number]; // x right, y up, z forward (nose)

const rot = ([x, y, z]: V, roll: number, pitch: number, yaw: number): V => {
  // right stick = right side down; pitch stick up = nose down; then yaw about the vertical axis
  let c = Math.cos(-roll), s = Math.sin(-roll); [x, y] = [x * c - y * s, x * s + y * c];
  c = Math.cos(pitch); s = Math.sin(pitch); [y, z] = [y * c - z * s, y * s + z * c];
  c = Math.cos(yaw); s = Math.sin(yaw); [x, z] = [x * c + z * s, -x * s + z * c];
  return [x, y, z];
};

export function drawDrone(ctx: CanvasRenderingContext2D, w: number, h: number, p: Pose, accent = '#C3F45C') {
  ctx.clearRect(0, 0, w, h);
  const tilt = 0.6, lift = (p.thr - 0.5) * 0.9;
  const cam = 0.42; // camera looks down at the quad from behind
  const project = (v: V): [number, number, number] => {
    const y = v[1] * Math.cos(cam) - v[2] * Math.sin(cam), z = v[1] * Math.sin(cam) + v[2] * Math.cos(cam) + 4.2;
    const k = (h * 0.62) / z;
    return [w / 2 + v[0] * k, h * 0.5 - y * k, z];
  };
  const place = (v: V): V => { const r = rot(v, p.roll * tilt, p.pitch * tilt, p.yaw); return [r[0], r[1] + lift, r[2]]; };

  // ground shadow, shrinking as the quad climbs
  const g = project([0, -1.3, 0]);
  ctx.fillStyle = 'rgba(0,0,0,0.35)';
  ctx.beginPath(); ctx.ellipse(g[0], g[1], w * (0.2 - lift * 0.08), h * 0.05, 0, 0, Math.PI * 2); ctx.fill();
  ctx.strokeStyle = 'rgba(160,185,210,0.25)'; ctx.lineWidth = 1;
  for (let i = -2; i <= 2; i++) {
    const a = project([i * 0.9, -1.3, -2]), b = project([i * 0.9, -1.3, 2]), c = project([-2.2, -1.3, i * 0.9]), d = project([2.2, -1.3, i * 0.9]);
    ctx.beginPath(); ctx.moveTo(a[0], a[1]); ctx.lineTo(b[0], b[1]); ctx.moveTo(c[0], c[1]); ctx.lineTo(d[0], d[1]); ctx.stroke();
  }

  const motors: { at: V; front: boolean; dir: number }[] = [
    { at: [0.85, 0, 0.85], front: true, dir: 1 }, { at: [-0.85, 0, 0.85], front: true, dir: -1 },
    { at: [0.85, 0, -0.85], front: false, dir: -1 }, { at: [-0.85, 0, -0.85], front: false, dir: 1 },
  ];
  const pm = motors.map((m) => ({ ...m, c: project(place(m.at)) })).sort((a, b) => b.c[2] - a.c[2]); // far first
  const hub = project(place([0, 0, 0]));

  // body and arms
  ctx.lineCap = 'round';
  ctx.strokeStyle = '#8fa3b8'; ctx.lineWidth = 5;
  for (const m of pm) { ctx.beginPath(); ctx.moveTo(hub[0], hub[1]); ctx.lineTo(m.c[0], m.c[1]); ctx.stroke(); }
  const body = ([[-0.28, 0.1, 0.45], [0.28, 0.1, 0.45], [0.28, 0.1, -0.45], [-0.28, 0.1, -0.45]] as V[]).map((v) => project(place(v)));
  ctx.fillStyle = '#1b2b3d'; ctx.strokeStyle = accent; ctx.lineWidth = 2;
  ctx.beginPath(); body.forEach((b, i) => (i ? ctx.lineTo(b[0], b[1]) : ctx.moveTo(b[0], b[1]))); ctx.closePath(); ctx.fill(); ctx.stroke();
  const nose = project(place([0, 0.1, 0.95])), noseL = project(place([-0.18, 0.1, 0.5])), noseR = project(place([0.18, 0.1, 0.5]));
  ctx.fillStyle = '#ff9a3c'; ctx.beginPath(); ctx.moveTo(nose[0], nose[1]); ctx.lineTo(noseL[0], noseL[1]); ctx.lineTo(noseR[0], noseR[1]); ctx.closePath(); ctx.fill();

  // propellers: discs in the quad's own plane, blades spin faster with throttle
  for (const m of pm) {
    const col = m.front ? '#ff9a3c' : accent;
    const ring = Array.from({ length: 28 }, (_, i) => { const t = (i / 28) * Math.PI * 2; return project(place([m.at[0] + Math.cos(t) * 0.5, 0.05, m.at[2] + Math.sin(t) * 0.5])); });
    ctx.fillStyle = col + '33'; ctx.strokeStyle = col; ctx.lineWidth = 2;
    ctx.beginPath(); ring.forEach((r, i) => (i ? ctx.lineTo(r[0], r[1]) : ctx.moveTo(r[0], r[1]))); ctx.closePath(); ctx.fill(); ctx.stroke();
    for (let b = 0; b < 2; b++) {
      const t = p.spin * m.dir * (0.4 + p.thr) + b * Math.PI;
      const a = project(place([m.at[0] + Math.cos(t) * 0.5, 0.05, m.at[2] + Math.sin(t) * 0.5])), c = project(place([m.at[0], 0.05, m.at[2]]));
      ctx.beginPath(); ctx.moveTo(c[0], c[1]); ctx.lineTo(a[0], a[1]); ctx.stroke();
    }
  }
}
