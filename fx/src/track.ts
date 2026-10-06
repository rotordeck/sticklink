// Type-only subset of stickcam's src/track.ts: the shape draw.ts reads. LiveFeed fills it from the live stream.
export interface Track {
  fps: number;
  frames: number;
  /** Time (s) of frame 0. */
  start: number;
  roll: Float32Array; pitch: Float32Array; yaw: Float32Array; // -1..1
  throttle: Float32Array; // 0..1
  gyro: [Float32Array, Float32Array, Float32Array];
  motor: Float32Array;
  live: Uint8Array;
}
