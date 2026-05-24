# hook_ffmpeg.py
# ─────────────────────────────────────────────────────────────
# PyInstaller runtime hook — runs before app.py starts.
# Points Whisper/ffmpeg to the bundled ffmpeg.exe inside the .exe package.
# Also suppresses the CMD window flash on Windows.
# ─────────────────────────────────────────────────────────────

import os
import sys
import subprocess

if getattr(sys, 'frozen', False):
    # ── Point to bundled ffmpeg ────────────────────────────────
    base = sys._MEIPASS
    ffmpeg_path  = os.path.join(base, 'ffmpeg.exe')
    ffprobe_path = os.path.join(base, 'ffprobe.exe')

    os.environ['PATH']            = base + os.pathsep + os.environ.get('PATH', '')
    os.environ['FFMPEG_BINARY']   = ffmpeg_path
    os.environ['FFPROBE_BINARY']  = ffprobe_path

# ── Suppress CMD window flash on Windows ──────────────────────
# Patch subprocess.Popen globally so every child process
# (including ffmpeg called by Whisper) runs hidden.
if sys.platform == "win32":
    _original_popen = subprocess.Popen

    class _SilentPopen(_original_popen):
        def __init__(self, *args, **kwargs):
            si = subprocess.STARTUPINFO()
            si.dwFlags  |= subprocess.STARTF_USESHOWWINDOW
            si.wShowWindow = subprocess.SW_HIDE
            kwargs.setdefault('startupinfo', si)
            super().__init__(*args, **kwargs)

    subprocess.Popen = _SilentPopen

