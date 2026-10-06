// Type-only subset of stickcam's src/motion.ts (+ gimbalPositions, copied verbatim).
import type { Track } from './track.ts';

export type EventKind = 'snap' | 'flip' | 'roll' | 'spin' | 'punch' | 'arm' | 'disarm' | 'crash' | 'full' | 'hang';

export interface MotionEvent {
  frame: number;
  kind: EventKind;
  side?: 0 | 1;
  x?: number; y?: number;
  turns?: number;
  dir?: number;
  combo?: number;
  label?: string;
  end?: number; t0?: number; dur?: number;
}

export interface MotionStats { fullTotal: Float32Array; hangBest: Float32Array; armedTime: Float32Array }

export interface Motion {
  lx: Float32Array; ly: Float32Array; rx: Float32Array; ry: Float32Array;
  speedL: Float32Array; speedR: Float32Array;
  events: MotionEvent[];
  stats: MotionStats;
}

/** Map a track frame to gimbal dot positions (y down: stick up = -1). */
export function gimbalPositions(tr: Track, i: number, mode: 1 | 2): [number, number, number, number] {
  const thrY = 1 - 2 * tr.throttle[i];
  const pitchY = -tr.pitch[i];
  return mode === 2
    ? [tr.yaw[i], thrY, tr.roll[i], pitchY]
    : [tr.yaw[i], pitchY, tr.roll[i], thrY];
}
