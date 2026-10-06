import json
import os
import socket
import tempfile
import time
import unittest
import urllib.request
from pathlib import Path

from sticklink.fxconfig import FxConfigStore
from sticklink.scenes import SceneStore
from sticklink.service import Service


def free_port():
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


class ServiceTests(unittest.TestCase):
    def make(self, port=None):
        tmp = Path(tempfile.mkdtemp())
        return Service(port or free_port(), fx_config=FxConfigStore(tmp/'fx.json'), scene_store=SceneStore(tmp/'scenes.json'))

    def test_start_serves_demo_and_stop_releases_the_port(self):
        svc = self.make()
        self.assertEqual(svc.status(), ('off', 'Stopped'))
        svc.start()
        try:
            self.assertTrue(svc.running)
            with urllib.request.urlopen(svc.url('/api/v1/state'), timeout=5) as r:
                self.assertEqual(r.status, 200)
            deadline = time.time()+5
            while svc.status()[0] != 'ok' and time.time() < deadline:
                time.sleep(0.1)
            self.assertEqual(svc.status()[0], 'ok')
        finally:
            svc.stop()
        self.assertFalse(svc.running)
        self.assertEqual(svc.status()[0], 'off')
        with socket.socket() as s:  # nothing listens any more (TIME_WAIT from the finished request is fine)
            if os.name != 'nt':
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind(('127.0.0.1', svc.http_port))

    def test_second_service_on_the_same_port_fails_cleanly(self):
        first = self.make()
        first.start()
        try:
            second = self.make(first.http_port)
            with self.assertRaises(OSError):
                second.start()
            self.assertFalse(second.running)
        finally:
            first.stop()

    def test_missing_radio_reports_waiting(self):
        svc = self.make()
        svc.start('/dev/does-not-exist')
        try:
            time.sleep(0.5)
            level, text = svc.status()
            self.assertEqual(level, 'wait')
            self.assertIn('Waiting for the radio', text)
        finally:
            svc.stop()


@unittest.skipUnless(os.environ.get('DISPLAY') or os.name == 'nt', 'needs a display')
class WindowTests(unittest.TestCase):
    def test_window_starts_and_stops_the_service(self):
        try:
            import customtkinter as ctk
            root = ctk.CTk()
        except Exception as exc:  # no tkinter / no X server
            self.skipTest(str(exc))
        from sticklink import gui
        tmp = Path(tempfile.mkdtemp())
        svc = Service(free_port(), fx_config=FxConfigStore(tmp/'fx.json'), scene_store=SceneStore(tmp/'scenes.json'))
        win = gui.Window(root, svc)
        try:
            self.assertEqual(win.button.cget('text'), 'Start')
            win.choice.set(gui.DEMO)
            win.toggle()
            self.assertTrue(svc.running)
            self.assertEqual(win.button.cget('text'), 'Stop')
            self.assertIn(str(svc.http_port), win.link.cget('text'))
            win.toggle()
            self.assertFalse(svc.running)
            self.assertEqual(win.button.cget('text'), 'Start')
        finally:
            svc.stop()
            root.destroy()


if __name__ == '__main__':
    unittest.main()
