// Fetches the installed themes from the server, registers them as styles and loads their fonts. Never throws: no themes = built-ins only.
import { registerThemes, type ThemeData } from './render/style.ts';

export async function loadThemes(): Promise<void> {
  try {
    const r = await fetch('/api/v1/themes', { cache: 'no-store' });
    if (!r.ok) return;
    const themes = ((await r.json()) as { themes: ThemeData[] }).themes;
    registerThemes(themes);
    for (const t of themes) {
      if (t.error) continue;
      for (const f of t.fonts ?? []) {
        const face = new FontFace(f.family, `url(${JSON.stringify(f.url)})`);
        face.load().then(() => (document.fonts as unknown as { add(f: FontFace): void }).add(face), () => { /* the style falls back to the next font in its list */ });
      }
    }
  } catch { /* offline or old server: built-in styles only */ }
}
