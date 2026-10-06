// Monotone cubic (PCHIP) helpers: smooth curves through real readings that never overshoot them.

/** Fritsch-Carlson tangent (dy/dx) at point k of (xs, ys); one-sided at the ends, 0 at local extrema. */
export function tangent(xs: number[], ys: number[], k: number): number {
  const last = xs.length - 1;
  const d = (a: number) => (ys[a + 1] - ys[a]) / (xs[a + 1] - xs[a]);
  if (last < 1) return 0;
  if (k === 0) return d(0);
  if (k === last) return d(last - 1);
  const d0 = d(k - 1), d1 = d(k);
  if (d0 * d1 <= 0) return 0;
  const h0 = xs[k] - xs[k - 1], h1 = xs[k + 1] - xs[k], w0 = 2 * h1 + h0, w1 = h1 + 2 * h0;
  return (w0 + w1) / (w0 / d0 + w1 / d1);
}

/** Cubic Hermite value at u in 0..1 between (y0, m0) and (y1, m1) over an interval of length h; clamped to the endpoints. */
export function hermite(y0: number, m0: number, y1: number, m1: number, h: number, u: number): number {
  const h00 = 2 * u ** 3 - 3 * u ** 2 + 1, h10 = u ** 3 - 2 * u ** 2 + u, h01 = -2 * u ** 3 + 3 * u ** 2, h11 = u ** 3 - u ** 2;
  const y = h00 * y0 + h10 * h * m0 + h01 * y1 + h11 * h * m1;
  return Math.max(Math.min(y0, y1), Math.min(Math.max(y0, y1), y));
}
