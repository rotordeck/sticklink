"""A very small window: pick the radio, Start / Stop, see the status, open the web pages."""
import os
import sys
import webbrowser
import tkinter as tk
from pathlib import Path

import customtkinter as ctk

from . import __version__
from .themes import ThemeError, ThemeStore
from . import radio_install
from .service import PAGES, Service, running_sticklink

DEMO = 'Demo (no radio)'
# OBS-style dark window (flat, 4px corners, dense) in the Rotordeck palette: olive-black ground, lime accent, mono labels.
Y = dict(window='#141611', base='#1D2019', input='#272B21', hover='#35392E', border='#35392E', text='#F1F2E9',
         muted='#A0A496', primary='#C3F45C', primary_hover='#D5FF83', on_primary='#141611', link='#C3F45C')
COLOURS = {'off': '#A0A496', 'wait': '#E5AF24', 'ok': '#C3F45C', 'bad': '#E33B57'}


def mark(root, size):
    """The Rotordeck mark (four props joined by crossed arms, on a lime tile) as a tk image, rasterised with 3x3 supersampling."""
    def seg(x, y, ax, ay, bx, by):
        dx, dy = bx - ax, by - ay
        t = max(0, min(1, ((x - ax) * dx + (y - ay) * dy) / (dx * dx + dy * dy)))
        return ((x - ax - t * dx) ** 2 + (y - ay - t * dy) ** 2) ** .5

    def inside(x, y):  # x, y in the 40x40 design space
        if min(x, y, 40 - x, 40 - y) < 0:
            return None
        cx, cy = min(x, 40 - x), min(y, 40 - y)
        if cx < 10 and cy < 10 and (10 - cx) ** 2 + (10 - cy) ** 2 > 100:
            return None  # outside the tile's rounded corner
        ink = min(seg(x, y, 11, 11, 29, 29), seg(x, y, 29, 11, 11, 29)) <= 1.5
        ink = ink or any(abs(((x - px) ** 2 + (y - py) ** 2) ** .5 - 6) <= 1.5 for px, py in ((11, 11), (29, 11), (11, 29), (29, 29)))
        return Y['window'] if ink else Y['primary']

    img = tk.PhotoImage(master=root, width=size, height=size)
    k = 40 / size
    for py in range(size):
        row = []
        for px in range(size):
            hits = [inside((px + (i + .5) / 3) * k, (py + (j + .5) / 3) * k) for i in range(3) for j in range(3)]
            lime, dark = hits.count(Y['primary']), hits.count(Y['window'])
            if lime + dark == 0:
                row.append(Y['window'])  # transparent corner: blend into the window
            else:
                f = dark / (lime + dark)
                row.append('#%02x%02x%02x' % tuple(round(int(Y['primary'][i:i + 2], 16) * (1 - f) + int(Y['window'][i:i + 2], 16) * f) for i in (1, 3, 5)))
        img.put('{' + ' '.join(row) + '}', to=(0, py))
    return img



# What an EdgeTX / OpenTX radio (or an RC transmitter in the same family) calls itself over USB.
RADIO_WORDS = ('radiomaster', 'edgetx', 'opentx', 'jumper', 'frsky', 'taranis', 'horus', 'tbs', 'crossfire', 'flysky', 'betaflight',
               'pocket', 'boxer', 'zorro', 'tx16', 'tx12', 'mt12', 'gx12', 'x9d', 'x10', 'x-lite', 'qx7', 'stm32', 'virtual com')
RADIO_VIDS = (0x1209, 0x0483)  # pid.codes (EdgeTX) and STMicroelectronics, whose VCP most radios use


def looks_like_radio(info):
    text = f'{info.description} {info.manufacturer or ""} {info.product or ""}'.lower()
    return info.vid in RADIO_VIDS or any(w in text for w in RADIO_WORDS)


def ports():
    """[(choice text, looks like a radio)], radios first. Linux lists every built-in serial port (ttyS0...) with no
    hardware id: those are never a radio."""
    try:
        from serial.tools.list_ports import comports
        found = [(f'{p.device}  {p.description}', looks_like_radio(p)) for p in comports() if p.hwid and p.hwid != 'n/a']
    except Exception:
        return []
    return sorted(found, key=lambda f: not f[1])


def hide_console():
    """A double-clicked Windows exe owns its console alone: hide it. From a terminal (shared) leave it."""
    if sys.platform != 'win32':
        return
    try:
        import ctypes
        kernel = ctypes.windll.kernel32
        if kernel.GetConsoleProcessList((ctypes.c_uint * 2)(), 2) == 1:
            ctypes.windll.user32.ShowWindow(kernel.GetConsoleWindow(), 0)
    except Exception:
        pass


class Dialog(ctk.CTkToplevel):
    """A pop-up in the window's own style. `buttons` are (label, value) pairs, the first is the primary one; `show()` returns the value
    of the clicked button (None if closed). With `spinner` it shows a spinning disk and calls `poll()` twice a second: a non-None
    result closes the dialog with that value."""

    def __init__(self, parent, message, buttons, spinner=False, poll=None):
        super().__init__(parent, fg_color=Y['window'])
        self.result, self.poll, self.angle = None, poll, 0
        self.title('Sticklink')
        self.resizable(False, False)
        self.transient(parent)
        body = ctk.CTkFrame(self, fg_color=Y['window'])
        body.grid(padx=18, pady=18)
        column = 0
        if spinner:
            self.disk = tk.Canvas(body, width=40, height=40, bg=Y['window'], highlightthickness=0)
            self.disk.grid(row=0, column=0, padx=(0, 14))
            column = 1
            self.spin()
        ctk.CTkLabel(body, text=message, text_color=Y['text'], wraplength=360, justify='left', anchor='w').grid(row=0, column=column, sticky='w')
        row = ctk.CTkFrame(body, fg_color=Y['window'])
        row.grid(row=1, column=0, columnspan=2, sticky='e', pady=(16, 0))
        for i, (label, value) in enumerate(reversed(buttons)):
            primary = i == len(buttons) - 1
            ctk.CTkButton(row, text=label, width=96, corner_radius=4, command=lambda v=value: self.finish(v),
                          fg_color=Y['primary'] if primary else Y['input'], hover_color=Y['primary_hover'] if primary else Y['hover'],
                          text_color=Y['on_primary'] if primary else Y['text']).grid(row=0, column=i, padx=(4, 0))
        self.protocol('WM_DELETE_WINDOW', lambda: self.finish(None))
        self.bind('<Escape>', lambda _: self.finish(None))
        self.update_idletasks()
        x = parent.winfo_rootx() + (parent.winfo_width() - self.winfo_reqwidth()) // 2
        y = parent.winfo_rooty() + (parent.winfo_height() - self.winfo_reqheight()) // 2
        self.geometry(f'+{max(x, 0)}+{max(y, 0)}')
        if poll:
            self.after(500, self.check)

    def spin(self):
        self.disk.delete('all')
        self.disk.create_oval(4, 4, 36, 36, outline=Y['border'], width=4)
        self.disk.create_arc(4, 4, 36, 36, start=self.angle, extent=100, style='arc', outline=Y['primary'], width=4)
        self.angle = (self.angle - 20) % 360
        self.spin_job = self.after(50, self.spin)

    def check(self):
        found = self.poll()
        if found is not None:
            self.finish(found)
        else:
            self.after(500, self.check)

    def finish(self, value):
        self.result = value
        if getattr(self, 'spin_job', None):
            self.after_cancel(self.spin_job)
        self.destroy()

    def show(self):
        self.wait_visibility()
        self.grab_set()
        self.focus_set()
        self.wait_window()
        return self.result


class Chooser(ctk.CTkToplevel):
    """A folder or file picker in the window's own style (the stock Tk one is not). `folder=True` picks a folder, otherwise a file whose
    suffix is in `suffixes` (any file when empty). `pick()` returns the chosen path as a string, None when cancelled."""

    def __init__(self, parent, title, folder=True, start=None, suffixes=()):
        super().__init__(parent, fg_color=Y['window'])
        self.folder, self.suffixes, self.result, self.chosen = folder, tuple(suffixes), None, None
        self.title(title)
        self.geometry('520x420')
        self.minsize(420, 320)
        self.transient(parent)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        bar = ctk.CTkFrame(self, fg_color=Y['window'])
        bar.grid(row=0, column=0, sticky='ew', padx=12, pady=(12, 6))
        bar.columnconfigure(1, weight=1)
        self.up = ctk.CTkButton(bar, text='Up', width=48, corner_radius=4, fg_color=Y['input'], hover_color=Y['hover'],
                                text_color=Y['text'], command=lambda: self.go(self.here.parent))
        self.up.grid(row=0, column=0, padx=(0, 6))
        self.path = ctk.CTkEntry(bar, corner_radius=4, fg_color=Y['input'], border_color=Y['border'], text_color=Y['text'])
        self.path.grid(row=0, column=1, sticky='ew')
        self.path.bind('<Return>', lambda _: self.go(Path(self.path.get()).expanduser()))
        self.items = ctk.CTkScrollableFrame(self, fg_color=Y['base'], corner_radius=4, scrollbar_button_color=Y['hover'],
                                            scrollbar_button_hover_color=Y['border'])
        self.items.grid(row=1, column=0, sticky='nsew', padx=12, pady=6)
        self.items.columnconfigure(0, weight=1)
        foot = ctk.CTkFrame(self, fg_color=Y['window'])
        foot.grid(row=2, column=0, sticky='ew', padx=12, pady=(6, 12))
        foot.columnconfigure(0, weight=1)
        self.note = ctk.CTkLabel(foot, text='', text_color=Y['muted'], anchor='w')
        self.note.grid(row=0, column=0, sticky='ew')
        ctk.CTkButton(foot, text='Cancel', width=96, corner_radius=4, fg_color=Y['input'], hover_color=Y['hover'], text_color=Y['text'],
                      command=self.destroy).grid(row=0, column=1, padx=(4, 0))
        self.select = ctk.CTkButton(foot, text='Select', width=96, corner_radius=4, fg_color=Y['primary'], hover_color=Y['primary_hover'],
                                    text_color=Y['on_primary'], command=self.finish)
        self.select.grid(row=0, column=2, padx=(4, 0))
        self.bind('<Escape>', lambda _: self.destroy())
        self.protocol('WM_DELETE_WINDOW', self.destroy)
        start = Path(start).expanduser() if start else Path.home()
        self.go(start if start.is_dir() else Path.home())
        self.update_idletasks()
        x = parent.winfo_rootx() + (parent.winfo_width() - self.winfo_width()) // 2
        y = parent.winfo_rooty() + (parent.winfo_height() - self.winfo_height()) // 2
        self.geometry(f'+{max(x, 0)}+{max(y, 0)}')

    def go(self, folder):
        try:
            entries = sorted(folder.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower()))
        except OSError as exc:
            self.note.configure(text=f'Cannot open: {exc.strerror or exc}')
            return
        self.here, self.chosen = folder, None
        self.path.delete(0, 'end')
        self.path.insert(0, str(folder))
        self.up.configure(state='normal' if folder.parent != folder else 'disabled')
        for child in self.items.winfo_children():
            child.destroy()
        shown = [e for e in entries if not e.name.startswith('.') and (e.is_dir() or (not self.folder and (not self.suffixes or e.suffix.lower() in self.suffixes)))]
        for row, entry in enumerate(shown):
            is_dir = entry.is_dir()
            ctk.CTkButton(self.items, text=('> ' if is_dir else '   ') + entry.name, anchor='w', corner_radius=4, fg_color='transparent',
                          hover_color=Y['hover'], text_color=Y['text'] if is_dir else Y['muted'],
                          command=lambda e=entry: self.click(e)).grid(row=row, column=0, sticky='ew', pady=1)
            # a double click opens a folder or takes a file
            self.items.winfo_children()[-1].bind('<Double-Button-1>', lambda _, e=entry: self.go(e) if e.is_dir() else self.finish(), add='+')
        if not shown:
            ctk.CTkLabel(self.items, text='Nothing to show here', text_color=Y['muted']).grid(row=0, column=0, pady=12)
        self.refresh()

    def click(self, entry):
        self.chosen = entry
        self.refresh()

    def refresh(self):
        target = self.chosen or (self.here if self.folder else None)
        ok = target is not None and (target.is_dir() if self.folder else target.is_file())
        self.select.configure(state='normal' if ok else 'disabled')
        self.note.configure(text=target.name or str(target) if target is not None else 'Choose a file')

    def finish(self):
        target = self.chosen or (self.here if self.folder else None)
        if target is None or (self.folder and not target.is_dir()) or (not self.folder and not target.is_file()):
            return
        self.result = str(target)
        self.destroy()

    def pick(self):
        self.wait_visibility()
        self.grab_set()
        self.focus_set()
        self.wait_window()
        return self.result


class Window:
    def __init__(self, root, service):
        self.root, self.service = root, service
        self.radios, self.chosen = set(), False
        root.title(f'Sticklink {__version__}')
        root.resizable(False, False)
        root.configure(fg_color=Y['window'])
        frame = ctk.CTkFrame(root, fg_color=Y['window'])
        frame.grid(padx=14, pady=14)
        self.icon, self.logo = mark(root, 64), mark(root, 32)
        try:
            root.iconphoto(True, self.icon)
        except tk.TclError:
            pass
        head = ctk.CTkFrame(frame, fg_color=Y['window'])
        head.grid(row=0, column=0, columnspan=2, sticky='we', pady=(0, 14))
        tk.Label(head, image=self.logo, bd=0, bg=Y['window']).grid(row=0, column=0, rowspan=2, padx=(0, 10))
        ctk.CTkLabel(head, text='Sticklink', text_color=Y['text'], font=ctk.CTkFont(size=20, weight='bold')).grid(row=0, column=1, sticky='w')
        ctk.CTkLabel(head, text=f'BY ROTORDECK  \u00b7  v{__version__}', text_color=Y['muted'], font=self.mono(10)).grid(row=1, column=1, sticky='w')
        ctk.CTkLabel(frame, text='RADIO', text_color=Y['muted'], font=self.mono(10)).grid(row=1, column=0, sticky='w')
        self.hint = ctk.CTkLabel(frame, text='', text_color=COLOURS['ok'], font=self.mono(10))
        self.hint.grid(row=1, column=0, columnspan=2, sticky='e')
        self.choice = ctk.CTkComboBox(frame, width=340, state='readonly', corner_radius=4, border_width=1, border_color=Y['border'],
                                      fg_color=Y['input'], button_color=Y['input'], button_hover_color=Y['hover'],
                                      dropdown_fg_color=Y['input'], dropdown_hover_color=Y['hover'], text_color=Y['text'], dropdown_text_color=Y['text'], text_color_disabled=Y['muted'])
        self.choice.configure(command=self.picked)
        self.choice.grid(row=2, column=0, sticky='we')
        self.small(frame, 'Refresh', self.refresh).grid(row=2, column=1, padx=(6, 0))
        self.button = ctk.CTkButton(frame, text='Start', command=self.toggle, corner_radius=4, height=32, fg_color=Y['primary'],
                                    hover_color=Y['primary_hover'], text_color=Y['on_primary'], text_color_disabled=Y['muted'],
                                    font=ctk.CTkFont(size=13, weight='bold'))
        self.button.grid(row=3, column=0, columnspan=2, sticky='we', pady=12)
        self.dot = ctk.CTkLabel(frame, text='●', font=ctk.CTkFont(size=18))
        self.dot.grid(row=4, column=0, sticky='w')
        self.status = ctk.CTkLabel(frame, text='', wraplength=380, justify='left')
        self.status.grid(row=4, column=0, sticky='w', padx=(26, 0), columnspan=2)
        tk.Frame(frame, bg=Y['border'], height=1).grid(row=5, column=0, columnspan=2, sticky='we', pady=12)
        self.link = ctk.CTkLabel(frame, text='', text_color=Y['link'], cursor='hand2', font=ctk.CTkFont(underline=True))
        self.link.grid(row=6, column=0, columnspan=2, sticky='w')
        self.link.bind('<Button-1>', lambda _: self.open('/fx'))
        pages = ctk.CTkFrame(frame, fg_color=Y['window'])
        pages.grid(row=7, column=0, columnspan=2, sticky='w', pady=(6, 0))
        self.page_buttons = []
        for i, (label, path) in enumerate(PAGES):
            b = self.small(pages, label, lambda p=path: self.open(p))
            b.grid(row=i // 3, column=i % 3, padx=(0, 4), pady=2)
            self.page_buttons.append(b)
        extra = ctk.CTkFrame(frame, fg_color=Y['window'])
        extra.grid(row=8, column=0, columnspan=2, sticky='w', pady=(8, 0))
        self.small(extra, 'Add theme...', self.add_theme).grid(row=0, column=0, padx=(0, 4))
        self.small(extra, 'Themes folder', self.open_themes).grid(row=0, column=1, padx=(0, 4))
        self.small(extra, 'Radio script...', self.install_script).grid(row=0, column=2)
        self.refresh()
        self.root.after(2000, self.rescan)
        self.tick()
        root.protocol('WM_DELETE_WINDOW', self.close)

    @staticmethod
    def mono(size):
        import tkinter.font
        return ctk.CTkFont(family=tkinter.font.nametofont('TkFixedFont').actual('family'), size=size)

    @staticmethod
    def small(parent, text, command):
        return ctk.CTkButton(parent, text=text, command=command, corner_radius=4, fg_color=Y['input'], hover_color=Y['hover'],
                             text_color=Y['text'], text_color_disabled=Y['muted'], width=112)

    def info(self, message):
        Dialog(self.root, message, [('OK', True)]).show()

    def error(self, message):
        Dialog(self.root, message, [('OK', True)]).show()

    def ask(self, message, yes='Yes', no='No'):
        return bool(Dialog(self.root, message, [(yes, True), (no, False)]).show())

    def refresh(self):
        found = ports()
        self.radios = {text for text, radio in found if radio}
        values = [DEMO] + [text for text, _ in found]
        self.choice.configure(values=values)
        current = self.choice.get()
        if current not in values or (current == DEMO and self.radios and not self.chosen):
            # pick a radio on our own (a RadioMaster, Jumper, ...), else any USB serial device, else the demo
            self.choice.set(values[1] if len(values) > 1 else values[0])
        self.radio_hint()

    def radio_hint(self):
        self.hint.configure(text='Radio found: ready to Start' if self.choice.get() in self.radios else '')

    def picked(self, value):
        self.chosen = True  # the user chose: stop picking for them
        self.radio_hint()

    def rescan(self):
        """While stopped, watch for the radio being plugged in or out."""
        if not self.service.running:
            self.refresh()
        self.root.after(2000, self.rescan)

    def selected_port(self):
        value = self.choice.get()
        return None if value == DEMO or not value else value.split('  ')[0]

    def toggle(self):
        if self.service.running:
            self.service.stop()
        else:
            try:
                self.service.start(self.selected_port())
            except OSError as exc:
                self.port_taken(exc)
        self.tick(once=True)

    def port_taken(self, exc):
        port = self.service.http_port
        other = running_sticklink(port)
        if other is not None:
            if self.ask(f'Sticklink {other} is already running on port {port} (another window or a terminal).\n\n'
                                   'Only one can use the radio at a time, so close the other one to start this one.\n\nOpen the running one\'s web portal?'):
                webbrowser.open(self.service.url('/'))
        else:
            self.error(f'Port {port} is used by another program ({exc}).\n\n'
                                 f'Close that program, or start Sticklink on another port:\nsticklink gui --http-port 47614')

    def install_script(self):
        cards = radio_install.find_cards()
        if not cards:
            cards = Dialog(self.root, 'SD card / controller not available.\n\nPlease connect your controller and put it in USB storage mode.',
                           [('Choose folder...', []), ('Cancel', None)], spinner=True, poll=lambda: radio_install.find_cards() or None).show()
            if cards is None:
                return
            if not cards:
                chosen = Chooser(self.root, 'Choose the radio SD card').pick()
                if not chosen:
                    return
                cards = [chosen]
        if len(cards) == 1:
            chosen = cards[0]
            if not self.ask(f'Found the radio SD card at {chosen}.\n\nInstall the Sticklink script (DDSTK.lua) on it?'):
                return
        else:
            self.info('Several radio cards found. Choose the one to use.')
            chosen = Chooser(self.root, 'Choose the radio SD card', start=cards[0].parent).pick()
            if not chosen:
                return
        try:
            dest = radio_install.install(chosen)
        except OSError as exc:
            self.error(f'Could not install the script:\n{exc}')
            return
        self.info(f'Installed {dest}.\n\nEject the card, then on the radio:\n'
                            '1. SYS > Hardware: set USB-VCP to LUA\n'
                            '2. MDL > Special Functions: ON, Lua Script, DDSTK\n'
                            '3. Restart the radio, plug it in and choose "USB Serial (VCP)".')

    def add_theme(self):
        source = Chooser(self.root, 'Choose a theme (.zip or .json)', folder=False, suffixes=('.zip', '.json')).pick()
        if not source:
            return
        store = (self.service.server_options.get('theme_store') or ThemeStore())
        try:
            try:
                name = store.install(source)
            except ThemeError as exc:
                if 'already installed' not in str(exc) or not self.ask(f'{exc}\n\nReplace it?'):
                    raise
                name = store.install(source, replace=True)
        except ThemeError as exc:
            self.error(f'Cannot install this theme:\n{exc}')
            return
        self.info(f'Installed "{name}". Pick it as the style in the overlay settings (double-click the overlay).')

    def open_themes(self):
        store = (self.service.server_options.get('theme_store') or ThemeStore())
        store.user_dir.mkdir(parents=True, exist_ok=True)
        webbrowser.open(store.user_dir.as_uri())

    def open(self, path):
        if self.service.running:
            webbrowser.open(self.service.url(path))

    def close(self):
        self.service.stop()
        self.root.destroy()

    def tick(self, once=False):
        running = self.service.running
        level, text = self.service.status()
        self.dot.configure(text_color=COLOURS[level])
        self.status.configure(text=text)
        self.button.configure(text='Stop' if running else 'Start')
        self.choice.configure(state='disabled' if running else 'readonly')
        self.link.configure(text=f'Web portal: {self.service.url()}' if running else 'Web portal: starts with Start')
        for b in self.page_buttons:
            b.configure(state='normal' if running else 'disabled')
        if not once:
            self.root.after(500, self.tick)


def main(http_port=47613):
    selftest = bool(os.environ.get('STICKLINK_GUI_SELFTEST'))  # CI: build the window, start/stop the demo, exit
    if not selftest:
        hide_console()
    if selftest:  # whatever is running on the usual port must not matter
        import socket
        with socket.socket() as probe:
            probe.bind(('127.0.0.1', 0))
            http_port = probe.getsockname()[1]
    ctk.set_appearance_mode('dark')
    root = ctk.CTk()
    service = Service(http_port)
    window = Window(root, service)
    if selftest:
        window.choice.set(DEMO)
        window.toggle()
        root.update()
        ok = service.running
        window.close()
        print('gui selftest', 'ok' if ok else 'FAILED')
        sys.exit(0 if ok else 1)
    import signal
    signal.signal(signal.SIGINT, lambda *_: root.after(0, window.close))  # Ctrl-C in the terminal closes the window cleanly
    root.mainloop()
