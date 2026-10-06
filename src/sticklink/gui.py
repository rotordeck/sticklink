"""A very small window: pick the radio, Start / Stop, see the status, open the web pages."""
import os
import sys
import webbrowser
import tkinter as tk
from tkinter import filedialog, messagebox

import customtkinter as ctk

from . import __version__
from .themes import ThemeError, ThemeStore
from .service import PAGES, Service, running_sticklink

DEMO = 'Demo (no radio)'
# Colours from OBS Studio's Yami theme, so the window looks at home next to OBS.
Y = dict(window='#1D1F26', base='#272A33', input='#3C404D', hover='#464B59', border='#5B6273', text='#FFFFFF',
         muted='#969696', primary='#284CB8', primary_hover='#476BD7', link='#718CDC')
COLOURS = {'off': '#969696', 'wait': '#E5AF24', 'ok': '#37D247', 'bad': '#E33B57'}


def ports():
    try:
        from serial.tools.list_ports import comports
        # Linux lists every built-in serial port (ttyS0...) with no hardware id: those are never a radio.
        return [f'{p.device}  {p.description}' for p in comports() if p.hwid and p.hwid != 'n/a']
    except Exception:
        return []


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


class Window:
    def __init__(self, root, service):
        self.root, self.service = root, service
        root.title(f'Sticklink {__version__}')
        root.resizable(False, False)
        root.configure(fg_color=Y['window'])
        frame = ctk.CTkFrame(root, fg_color=Y['window'])
        frame.grid(padx=14, pady=14)
        ctk.CTkLabel(frame, text='Radio', text_color=Y['muted']).grid(row=0, column=0, sticky='w')
        self.choice = ctk.CTkComboBox(frame, width=340, state='readonly', corner_radius=4, border_width=1, border_color=Y['border'],
                                      fg_color=Y['input'], button_color=Y['input'], button_hover_color=Y['hover'],
                                      dropdown_fg_color=Y['input'], dropdown_hover_color=Y['primary'], text_color_disabled=Y['muted'])
        self.choice.grid(row=1, column=0, sticky='we')
        self.small(frame, 'Refresh', self.refresh).grid(row=1, column=1, padx=(6, 0))
        self.button = ctk.CTkButton(frame, text='Start', command=self.toggle, corner_radius=4, height=32, fg_color=Y['primary'],
                                    hover_color=Y['primary_hover'], text_color_disabled=Y['muted'])
        self.button.grid(row=2, column=0, columnspan=2, sticky='we', pady=12)
        self.dot = ctk.CTkLabel(frame, text='●', font=ctk.CTkFont(size=18))
        self.dot.grid(row=3, column=0, sticky='w')
        self.status = ctk.CTkLabel(frame, text='', wraplength=380, justify='left')
        self.status.grid(row=3, column=0, sticky='w', padx=(26, 0), columnspan=2)
        tk.Frame(frame, bg=Y['input'], height=1).grid(row=4, column=0, columnspan=2, sticky='we', pady=12)
        self.link = ctk.CTkLabel(frame, text='', text_color=Y['link'], cursor='hand2', font=ctk.CTkFont(underline=True))
        self.link.grid(row=5, column=0, columnspan=2, sticky='w')
        self.link.bind('<Button-1>', lambda _: self.open('/fx'))
        pages = ctk.CTkFrame(frame, fg_color=Y['window'])
        pages.grid(row=6, column=0, columnspan=2, sticky='w', pady=(6, 0))
        self.page_buttons = []
        for i, (label, path) in enumerate(PAGES):
            b = self.small(pages, label, lambda p=path: self.open(p))
            b.grid(row=i // 3, column=i % 3, padx=(0, 4), pady=2)
            self.page_buttons.append(b)
        extra = ctk.CTkFrame(frame, fg_color=Y['window'])
        extra.grid(row=7, column=0, columnspan=2, sticky='w', pady=(8, 0))
        self.small(extra, 'Add theme...', self.add_theme).grid(row=0, column=0, padx=(0, 4))
        self.small(extra, 'Themes folder', self.open_themes).grid(row=0, column=1)
        self.refresh()
        self.tick()
        root.protocol('WM_DELETE_WINDOW', self.close)

    @staticmethod
    def small(parent, text, command):
        return ctk.CTkButton(parent, text=text, command=command, corner_radius=4, fg_color=Y['input'], hover_color=Y['hover'],
                             text_color_disabled=Y['muted'], width=112)

    def refresh(self):
        values = [DEMO] + ports()
        self.choice.configure(values=values)
        if self.choice.get() not in values:
            self.choice.set(values[1] if len(values) > 1 else values[0])  # first USB serial device, else demo

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
            if messagebox.askyesno('Sticklink', f'Sticklink {other} is already running on port {port} (another window or a terminal).\n\n'
                                   'Only one can use the radio at a time, so close the other one to start this one.\n\nOpen the running one\'s web portal?'):
                webbrowser.open(self.service.url('/'))
        else:
            messagebox.showerror('Sticklink', f'Port {port} is used by another program ({exc}).\n\n'
                                 f'Close that program, or start Sticklink on another port:\nsticklink gui --http-port 47614')

    def add_theme(self):
        source = filedialog.askopenfilename(title='Choose a theme (.zip or .json)', filetypes=[('Theme', '*.zip *.json'), ('All files', '*')])
        if not source:
            return
        store = (self.service.server_options.get('theme_store') or ThemeStore())
        try:
            try:
                name = store.install(source)
            except ThemeError as exc:
                if 'already installed' not in str(exc) or not messagebox.askyesno('Sticklink', f'{exc}\n\nReplace it?'):
                    raise
                name = store.install(source, replace=True)
        except ThemeError as exc:
            messagebox.showerror('Sticklink', f'Cannot install this theme:\n{exc}')
            return
        messagebox.showinfo('Sticklink', f'Installed "{name}". Pick it as the style in the overlay settings (double-click the overlay).')

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
