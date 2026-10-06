// Where each HUD block goes. Blocks are designed at a fixed size and scaled uniformly, so they never distort.
export type Block = 'link' | 'battery' | 'gps' | 'status' | 'race';
export interface Rect { x: number; y: number; w: number; h: number }
export interface Placed extends Rect { scale: number } // scale applies to the block's design size

/** Design size of every block, in design units. */
export const DESIGN: Record<Block, { w: number; h: number }> = {
  link: { w: 400, h: 280 }, battery: { w: 400, h: 250 }, gps: { w: 560, h: 420 }, status: { w: 560, h: 110 }, race: { w: 560, h: 300 },
};
const ORDER: Block[] = ['link', 'battery', 'gps', 'status', 'race'];
const REF = { w: 1920, h: 1080 };

const place = (block: Block, x: number, y: number, scale: number): Placed => ({ x, y, w: DESIGN[block].w * scale, h: DESIGN[block].h * scale, scale });

/** One block alone (its own page / OBS source): centred, as large as fits with a margin. */
export function layoutSingle(block: Block, W: number, H: number): Placed {
  const d = DESIGN[block], scale = Math.min((W * 0.94) / d.w, (H * 0.94) / d.h);
  return place(block, (W - d.w * scale) / 2, (H - d.h * scale) / 2, scale);
}

/** The combined HUD. `enabled` blocks only; the rest of the screen stays free for the video. */
export function layoutHud(layout: 'corners' | 'row' | 'column', enabled: Block[], W: number, H: number): Partial<Record<Block, Placed>> {
  const blocks = ORDER.filter((b) => enabled.includes(b)), out: Partial<Record<Block, Placed>> = {};
  if (!blocks.length) return out;
  const u = Math.min(W / REF.w, H / REF.h), m = 40 * u, gap = 24 * u;

  if (layout === 'corners') {
    const s = u; // designed for the reference size, scaled with the screen
    const corner: Record<Block, [number, number]> = {
      link: [m, m],
      battery: [m, H - m - DESIGN.battery.h * s],
      gps: [W - m - DESIGN.gps.w * s, H - m - DESIGN.gps.h * s],
      status: [W - m - DESIGN.status.w * s, m],
      race: [(W - DESIGN.race.w * s) / 2, m], // top centre, between Link and Status
    };
    for (const b of blocks) out[b] = place(b, corner[b][0], corner[b][1], s);
    return out;
  }
  if (layout === 'row') { // along the bottom, left to right, shrunk to fit the width
    const sum = blocks.reduce((a, b) => a + DESIGN[b].w, 0), s = Math.min(u * 1.2, (W - 2 * m - gap * (blocks.length - 1)) / sum);
    let x = (W - (sum * s + gap * (blocks.length - 1))) / 2;
    for (const b of blocks) { out[b] = place(b, x, H - m - DESIGN[b].h * s, s); x += DESIGN[b].w * s + gap; }
    return out;
  }
  // column: stacked down the left edge, shrunk to fit the height
  const sum = blocks.reduce((a, b) => a + DESIGN[b].h, 0), maxW = Math.max(...blocks.map((b) => DESIGN[b].w));
  const s = Math.min(u * 1.2, (H - 2 * m - gap * (blocks.length - 1)) / sum, (W - 2 * m) / maxW);
  let y = (H - (sum * s + gap * (blocks.length - 1))) / 2;
  for (const b of blocks) { out[b] = place(b, m, y, s); y += DESIGN[b].h * s + gap; }
  return out;
}
