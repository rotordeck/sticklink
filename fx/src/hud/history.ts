// Short rolling histories for sparklines, sampled at a fixed interval so a busy sensor does not flush the buffer.

export class History {
  private data = new Map<string, number[]>();
  private last = new Map<string, number>();
  private intervalMs: number;
  private size: number;
  constructor(intervalMs = 250, size = 120) { this.intervalMs = intervalMs; this.size = size; }

  push(key: string, value: number, now: number) {
    if (now - (this.last.get(key) ?? -Infinity) < this.intervalMs) return;
    this.last.set(key, now);
    const list = this.data.get(key) ?? [];
    list.push(value);
    if (list.length > this.size) list.shift();
    this.data.set(key, list);
  }

  series(key: string): readonly number[] { return this.data.get(key) ?? []; }
  reset() { this.data.clear(); this.last.clear(); }
}
