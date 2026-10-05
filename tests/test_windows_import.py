"""Imports the Windows package on a non-Windows host with fake Win32 bindings.

Catches broken imports and wiring in multicapture.platform.windows. It cannot execute any
real Win32/COM/D3D code, so it says nothing about runtime behaviour on Windows.
"""
import os
import subprocess
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SCRIPT = r'''
import ctypes, ctypes.wintypes, os, queue, shutil, subprocess, sys, threading, time, uuid, json, base64, socket, struct
import dataclasses, datetime, tempfile, urllib.parse, platform as _stdlib_platform
from unittest import mock

ctypes.WinDLL = lambda *a, **k: mock.MagicMock(name="WinDLL")
ctypes.windll = mock.MagicMock(name="windll")
ctypes.WINFUNCTYPE = ctypes.CFUNCTYPE
ctypes.WinError = lambda *a, **k: OSError("WinError")
ctypes.get_last_error = lambda: 0
ctypes.FormatError = lambda *a: "error"
ctypes.HRESULT = ctypes.c_long
sys.modules["winreg"] = mock.MagicMock(name="winreg")
sys.getwindowsversion = lambda: mock.Mock(build=22631)
os.startfile = mock.MagicMock(name="startfile", create=True)
sys.platform = "win32"
sys.path.insert(0, ROOT)

import multicapture.platform as osp
import multicapture.platform.windows as win
from multicapture.platform import base
import multicapture.config, multicapture.ffmpeg, multicapture.recorder, multicapture.splitjob, multicapture.browser
from multicapture.platform.windows import browser as wbrowser, pipe, wgc, loopback, win32, audiosession

import re
block = base.__doc__.split("Module-level names every implementation exports:")[1]
names = set()
for line in block.splitlines():
    m = re.match(r"    ([A-Za-z_][A-Za-z_0-9, ]*?)(?:\(|\s{2,}|$)", line)
    if m and not line.startswith("     "):
        names.update(n.strip() for n in m.group(1).split(",") if n.strip())
missing = [n for n in sorted(names) if not hasattr(osp, n)]
assert not missing, missing
assert len(names) > 25

assert osp.NAME == "windows" and osp.AudioPipe is pipe.AudioPipe
assert osp.BrowserWindow is wbrowser.BrowserWindow and hasattr(osp.BrowserWindow, "restore_if_minimized")
assert multicapture.browser.BrowserWindow is wbrowser.BrowserWindow
assert multicapture.browser.RENDER_FLAGS is __import__("multicapture.browser_common", fromlist=["x"]).RENDER_FLAGS
assert osp.SpeakerMute is audiosession.SpeakerMute and osp.KeepAwake is win32.KeepAwake
assert osp.thread_init is win32.ensure_mta and osp.clock.now is time.perf_counter
assert osp.popen_kwargs() == {"creationflags": 0x08000000}
assert osp.FFMPEG_NAME == "ffmpeg.exe" and osp.DEFAULT_BROWSER == "edge" and osp.TK_THEME == "vista"
assert osp.UI_FONT == "Yu Gothic UI" and osp.SCHEDULE_SUPPORTED is True and not osp.MUTE_VIA_CAPTURE and not osp.DISPLAY_ALWAYS_ON
assert osp.ffmpeg_candidates("C:/app") == [os.path.join("C:/app", "ffmpeg", "ffmpeg.exe"), os.path.join("C:/app", "ffmpeg.exe"), os.path.join("C:/app", "_internal", "ffmpeg.exe")]
assert osp.default_output_dir().endswith(os.path.join("Videos", "MultiCapture"))
assert osp.check_environment() is None
sys.getwindowsversion = lambda: mock.Mock(build=19045)
assert "Windows 11" in osp.check_environment()
assert osp.open_folder is not None and osp.primary_screen_size is win32.primary_screen_size

assert osp.HW_ENCODERS == ["h264_nvenc", "h264_amf", "h264_qsv"]
assert osp.OVERLAP_HINT == "録画中のウィンドウは重なっていても裏に隠れていてもOK（最小化のみ不可）"
import multicapture.capacity
assert multicapture.capacity.default_pix_fmt() == "bgra"

# detect_encoder probes HW_ENCODERS in order, then falls back to libx264
probed = []
multicapture.ffmpeg._works = lambda ff, enc: probed.append(enc) or enc == "h264_amf"
multicapture.ffmpeg._detected = None
assert multicapture.ffmpeg.detect_encoder("ffmpeg") == "h264_amf" and probed == ["h264_nvenc", "h264_amf"], probed
multicapture.ffmpeg._works = lambda ff, enc: False
multicapture.ffmpeg._detected = None
assert multicapture.ffmpeg.detect_encoder("ffmpeg") == "libx264"
assert multicapture.ffmpeg.detect_encoder("ffmpeg", "h264_qsv") == "h264_qsv"

# open_window_capture wiring: D3DDevice + WindowCapture(hwnd, device), closed capture-then-device
calls = []
class FakeDevice:
    def close(self): calls.append("device.close")
def fake_init(self, hwnd, device):
    calls.append(("capture", hwnd, type(device).__name__))
wgc.D3DDevice = FakeDevice
wgc.WindowCapture.__init__ = fake_init
wgc.WindowCapture.close = lambda self: calls.append("capture.close")
class Bw:
    hwnd = 1234
    pid = 55
cap = osp.open_window_capture(Bw)
assert isinstance(cap, wgc.WindowCapture) and cap.pix_fmt == "bgra"
assert calls == [("capture", 1234, "FakeDevice")], calls
cap.close()
assert calls[1:] == ["capture.close", "device.close"], calls

# a failing WindowCapture constructor must not leak the device
calls.clear()
def bad_init(self, hwnd, device):
    raise OSError("boom")
wgc.WindowCapture.__init__ = bad_init
try:
    osp.open_window_capture(Bw)
except OSError:
    pass
else:
    raise AssertionError("expected OSError")
assert calls == ["device.close"], calls

# open_audio_capture wiring
made = []
loopback.ProcessLoopback = lambda pid, rate, ch: made.append((pid, rate, ch)) or "loop"
assert osp.open_audio_capture(Bw, 48000, 2, mute=True) == "loop" and made == [(55, 48000, 2)]

# recorder / splitjob pick up the Windows adapters
assert multicapture.recorder.osp.open_window_capture is osp.open_window_capture
assert multicapture.splitjob.osp.SpeakerMute is audiosession.SpeakerMute
'''


class WindowsImportTests(unittest.TestCase):
    def test_windows_package_imports_and_wiring(self):
        code = "ROOT = %r\n" % ROOT + SCRIPT
        proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)


class BuildCommandIdenticalTests(unittest.TestCase):
    """ffmpeg.build_command (refactored to share video_encode_args) must match the 1.2.1 original (e111bb8) byte for byte."""

    @staticmethod
    def original_module():
        try:
            src = subprocess.run(["git", "show", "e111bb8:multicapture/ffmpeg.py"], cwd=ROOT, capture_output=True,
                                 text=True, encoding="utf-8", timeout=30, check=True).stdout
        except (OSError, subprocess.SubprocessError):
            return None
        sys.path.insert(0, ROOT)
        import types
        from multicapture.config import app_dir
        module = types.ModuleType("ffmpeg_head")
        exec(compile(src.replace("from .config import app_dir", "app_dir = None"), "ffmpeg_head", "exec"), module.__dict__)
        return module

    def test_commands_unchanged(self):
        old = self.original_module()
        if old is None:
            self.skipTest("git history not available")
        from multicapture import ffmpeg as new
        cases = [
            dict(width=1920, height=1080, fps=30, out_w=1920, out_h=1080, encoder="h264_nvenc", output="out.mp4"),
            dict(width=1280, height=720, fps=60, out_w=1920, out_h=1080, encoder="h264_amf", output="C:/x/out.mkv"),
            dict(width=1920, height=1080, fps=30, out_w=1920, out_h=1080, encoder="h264_qsv", output="p.mkv",
                 trim_start=2.5, no_bframes=True, key_frames=[1.5, 3.25]),
            dict(width=1920, height=1080, fps=30, out_w=1920, out_h=1080, encoder="libx264", output="p.mp4",
                 trim_start=2.5, no_bframes=True, key_frames=[1.5]),
        ]
        for case in cases:
            with self.subTest(encoder=case["encoder"], output=case["output"]):
                kw = dict(case)
                args = (kw.pop("width"), kw.pop("height"), kw.pop("fps"))
                a = old.build_command("ffmpeg.exe", *args, "\\\\.\\pipe\\x", 48000, 2, kw.pop("out_w"), kw.pop("out_h"),
                                      kw.pop("encoder"), kw.pop("output"), **kw)
                kw2 = dict(case)
                b = new.build_command("ffmpeg.exe", kw2["width"], kw2["height"], kw2["fps"], "\\\\.\\pipe\\x", 48000, 2,
                                      kw2["out_w"], kw2["out_h"], kw2["encoder"], kw2["output"],
                                      **{k: v for k, v in kw2.items() if k in ("trim_start", "no_bframes", "key_frames")})
                self.assertEqual(a, b)


if __name__ == "__main__":
    unittest.main()
