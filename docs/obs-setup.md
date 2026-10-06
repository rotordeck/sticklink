# OBS setup

Sticklink serves web pages; OBS shows them with its **Browser** source. The program must be running while you stream.

## Add the overlay

1. In **Sources** click **+** and choose **Browser**.
2. **URL**: `http://127.0.0.1:47613/fx` (use `/overlay` for the plain panel; change the port if you started Sticklink with `--http-port`).
3. Leave **Local file** off.
4. **Width x Height**: **576 x 450** is recommended (the settings panel shows the size for your settings). Any size works: the
   overlay fills the whole source and keeps the gimbals in its middle, and it shrinks to fit if the source is small. Resize
   the source freely in OBS; there is no need to match a number exactly.
5. Tick **Use custom frame rate** and enter **60**. At OBS's default 30 fps the smooth trails look choppy.
6. Leave the default custom CSS: the page is transparent, so no chroma key is needed.
7. Turn off **Shutdown source when not visible** and **Refresh browser when scene becomes active**, so the connection stays up.
8. OK, then position and scale the source in your scene.

## The telemetry HUD

`/hud` is meant to cover the whole video: add it as a Browser Source the size of your canvas (for example 1920 x 1080) and put it above the video.
To place blocks yourself, add `/hud/link`, `/hud/battery` and `/hud/gps` as separate Browser Sources (any size; each block fills its source, centred),
then move and resize them in your scene. The GPS block needs internet for the map tiles; without it the block shows the track only.

## Different looks in different sources

By default every source shows the settings saved on the server, so they all change together. To give a source its **own** look, open the settings
panel, copy the *link to this configuration* and use it as that source's URL. A link source ignores the saved settings (see
[permanent links](overlay-guide.md#permanent-links)).

## Change the look from OBS

Right-click the source, choose **Interact**, then double-click inside the window: the settings panel opens. Changes are
saved by Sticklink itself, so you can also open `http://127.0.0.1:47613/fx` in any browser and change the settings there;
the OBS source follows within about two seconds.

If the overlay runs slightly ahead of your video, raise **Video delay (ms)** in the panel.

## No "Browser" source in the list

The browser source needs OBS's embedded Chromium (CEF), and not every build includes it.

- **Windows and macOS**: the official OBS download includes it.
- **Linux**: the official Flatpak (`com.obsproject.Studio`) includes it. Some distribution packages do not. On Arch and
  derivatives the plain `obs-studio` package has no browser source; the AUR package `obs-studio-browser` replaces it with a
  build that has one.

## OBS crashes after the browser source appears (Linux, Wayland)

Seen on Arch/CachyOS with OBS 32 and an AMD GPU: the browser engine's GPU process crashed repeatedly and took OBS down.
Turning browser hardware acceleration off fixed it: **Settings, Advanced, "Enable browser source hardware acceleration"**
off, or, with OBS closed, set `BrowserHWAccel=false` in `~/.config/obs-studio/global.ini`. Starting OBS through XWayland
(`QT_QPA_PLATFORM=xcb obs`) is another thing to try. This costs some CPU for every browser source.

## Switching scenes with your radio

Sticklink can also change OBS's scene from your radio's switches over OBS's WebSocket server (Tools, WebSocket Server Settings). See [scene switching](scenes.md).

## Without the browser source

You can capture a normal browser window showing `/fx` with a window or screen capture. Capture cannot keep transparency,
so the overlay would sit on a solid background; there is no built-in chroma-key background option yet.
