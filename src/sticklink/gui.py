"""A very small window: pick the radio, Start / Stop, see the status, open the web pages."""
import os
import sys
import webbrowser
import tkinter as tk
from tkinter import messagebox, ttk

from . import __version__
from .service import Service

DEMO = 'Demo (no radio)'
PAGES = (('Overlay for OBS', '/fx'), ('Setup', '/setup'), ('Scene switching', '/modes'),
         ('Telemetry HUD', '/hud'), ('API docs', '/docs'))
COLOURS = {'off': '#888888', 'wait': '#d98e04', 'ok': '#1a9b3c', 'bad': '#c0392b'}


def ports():
    try:
        from serial.tools.list_ports import comports
        return [f'{p.device}  {p.description}' for p in comports()]
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
        frame = ttk.Frame(root, padding=14)
        frame.grid()
        ttk.Label(frame, text='Radio').grid(row=0, column=0, sticky='w')
        self.choice = ttk.Combobox(frame, width=44, state='readonly')
        self.choice.grid(row=1, column=0, sticky='we')
        ttk.Button(frame, text='Refresh', command=self.refresh).grid(row=1, column=1, padx=(6, 0))
        self.button = ttk.Button(frame, text='Start', command=self.toggle)
        self.button.grid(row=2, column=0, columnspan=2, sticky='we', pady=10)
        self.dot = tk.Label(frame, text='●', font=('TkDefaultFont', 16))
        self.dot.grid(row=3, column=0, sticky='w')
        self.status = ttk.Label(frame, text='', wraplength=380, justify='left')
        self.status.grid(row=3, column=0, sticky='w', padx=(26, 0), columnspan=2)
        ttk.Separator(frame).grid(row=4, column=0, columnspan=2, sticky='we', pady=10)
        self.link = tk.Label(frame, text='', fg='#1a5fb4', cursor='hand2', font=('TkDefaultFont', 10, 'underline'))
        self.link.grid(row=5, column=0, columnspan=2, sticky='w')
        self.link.bind('<Button-1>', lambda _: self.open('/fx'))
        pages = ttk.Frame(frame)
        pages.grid(row=6, column=0, columnspan=2, sticky='w', pady=(6, 0))
        self.page_buttons = []
        for i, (label, path) in enumerate(PAGES):
            b = ttk.Button(pages, text=label, command=lambda p=path: self.open(p))
            b.grid(row=i // 3, column=i % 3, padx=(0, 4), pady=2)
            self.page_buttons.append(b)
        self.refresh()
        self.tick()
        root.protocol('WM_DELETE_WINDOW', self.close)

    def refresh(self):
        self.choice['values'] = [DEMO] + ports()
        if self.choice.get() not in self.choice['values']:
            self.choice.current(1 if len(self.choice['values']) > 1 else 0)  # first real radio, else demo

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
                messagebox.showerror('Sticklink', f'Cannot start on {self.service.url()}:\n{exc}\n\n'
                                     'Is Sticklink already running (another window or a terminal)?')
        self.tick(once=True)

    def open(self, path):
        if self.service.running:
            webbrowser.open(self.service.url(path))

    def close(self):
        self.service.stop()
        self.root.destroy()

    def tick(self, once=False):
        running = self.service.running
        level, text = self.service.status()
        self.dot.configure(fg=COLOURS[level])
        self.status.configure(text=text)
        self.button.configure(text='Stop' if running else 'Start')
        self.choice.configure(state='disabled' if running else 'readonly')
        self.link.configure(text=f'Web portal: {self.service.url()}' if running else 'Web portal: starts with Start')
        for b in self.page_buttons:
            b.state(['!disabled'] if running else ['disabled'])
        if not once:
            self.root.after(500, self.tick)


def main(http_port=8765):
    selftest = bool(os.environ.get('STICKLINK_GUI_SELFTEST'))  # CI: build the window, start/stop the demo, exit
    if not selftest:
        hide_console()
    if selftest:  # whatever is running on the usual port must not matter
        import socket
        with socket.socket() as probe:
            probe.bind(('127.0.0.1', 0))
            http_port = probe.getsockname()[1]
    root = tk.Tk()
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
    root.mainloop()
