// Transport + delay buffer, independent of any drawing. Reusable by any overlay.
export class StickLinkClient {
  constructor(delayMs = 0) {
    this.delayMs = delayMs;
    this.queue = []; this.latest = null; this.displayState = null;
    this.lastMessage = 0; this.mounted = false;
  }
  start() { this.mounted = true; this.connect(); }
  stop() {
    this.mounted = false; clearTimeout(this.retry);
    this.socket?.close(); this.queue = []; this.latest = null;
  }
  connect() {
    if (!this.mounted) return;
    const url = `${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/ws`;
    this.socket = new WebSocket(url);
    this.socket.onmessage = event => {
      try {
        const state = JSON.parse(event.data);
        if (state.schema !== 1) return;
        const now = performance.now();
        this.lastMessage = now;
        // Drop earlier buffered states on a radio reconnect/restart.
        if (this.latest && state.session !== this.latest.session) this.queue = [];
        this.latest = state;
        this.queue.push({at: now + this.delayMs, state});
        if (this.queue.length > 200) this.queue.shift();
      } catch (_) { /* next well-formed frame recovers */ }
    };
    this.socket.onclose = () => {
      this.latest = null; this.queue = []; this.displayState = null;
      if (this.mounted) this.retry = setTimeout(() => this.connect(), 1000);
    };
    this.socket.onerror = () => this.socket.close();
  }
  // Advance the delay buffer; returns what to draw now.
  step() {
    const now = performance.now();
    let target = null;
    while (this.queue.length && this.queue[0].at <= now) target = this.queue.shift().state;
    if (target) this.displayState = target;
    const transportLive = this.socket?.readyState === WebSocket.OPEN && now - this.lastMessage < 1000;
    return {state: this.displayState, transportLive};
  }
}
