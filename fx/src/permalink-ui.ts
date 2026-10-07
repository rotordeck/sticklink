// The "link to this configuration" row shared by the settings panels: a read-only field with the permanent URL and a Copy button.
// The browser's address bar is never touched; only this field changes as settings change.

export const LINK_CSS = `
  .linkrow{display:flex;gap:6px;align-items:center;margin-top:4px}
  .linkrow input{flex:1;min-width:0;max-width:none;width:auto;background:#272B21;color:#F1F2E9;border:1px solid #35392E;border-radius:4px;padding:3px 5px;font:11px monospace}
  .linkrow button{margin-top:0;white-space:nowrap}`;

export const LINK_HTML = `
  <h4>LINK TO THIS CONFIGURATION</h4>
  <div class="linkrow"><input type="text" name="permalink" readonly spellcheck="false"><button type="button" class="copy">Copy</button></div>
  <div class="hint linknote"></div>`;

export class LinkRow {
  private input: HTMLInputElement;
  private note: HTMLElement;
  private button: HTMLButtonElement;
  private timer = 0;

  constructor(panel: HTMLElement) {
    this.input = panel.querySelector('[name="permalink"]') as HTMLInputElement;
    this.note = panel.querySelector('.linknote') as HTMLElement;
    this.button = panel.querySelector('.copy') as HTMLButtonElement;
    this.input.addEventListener('focus', () => this.input.select());
    this.button.addEventListener('click', () => { void this.copy(); });
  }

  /** Show the link for the current configuration. `pinned`: this page was itself opened from a link. */
  update(url: string, pinned: boolean) {
    if (this.input.value !== url) this.input.value = url;
    this.note.textContent = pinned
      ? 'This page was opened from a link, so changes here are not saved on the server. Copy this link to keep this look.'
      : 'Settings are saved on the server. This link reproduces exactly this configuration on any page, whatever is saved there.';
  }

  private async copy() {
    let ok = false;
    try { await navigator.clipboard.writeText(this.input.value); ok = true; } catch { /* clipboard blocked: fall back */ }
    if (!ok) { this.input.select(); try { ok = document.execCommand('copy'); } catch { ok = false; } }
    this.button.textContent = ok ? 'Copied ✓' : 'Select + Ctrl+C';
    clearTimeout(this.timer);
    this.timer = window.setTimeout(() => { this.button.textContent = 'Copy'; }, 1800);
  }
}
