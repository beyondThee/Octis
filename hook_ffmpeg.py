# hook_ffmpeg.py
# ─────────────────────────────────────────────────────────────
# PyInstaller runtime hook — runs before app.py starts.
# Points Whisper to bundled ffmpeg on both Windows and Mac.
# Also suppresses CMD window flash on Windows.
# ─────────────────────────────────────────────────────────────

import os
import sys
import subprocess

if getattr(sys, 'frozen', False):
    base         = sys._MEIPASS
    ffmpeg_name  = 'ffmpeg.exe' if sys.platform == 'win32' else 'ffmpeg'
    ffprobe_name = 'ffprobe.exe' if sys.platform == 'win32' else 'ffprobe'

    ffmpeg_path  = os.path.join(base, ffmpeg_name)
    ffprobe_path = os.path.join(base, ffprobe_name)

    os.environ['PATH']           = base + os.pathsep + os.environ.get('PATH', '')
    os.environ['FFMPEG_BINARY']  = ffmpeg_path
    os.environ['FFPROBE_BINARY'] = ffprobe_path

# ── Suppress CMD window flash on Windows ──────────────────────
if sys.platform == 'win32':
    _original_popen = subprocess.Popen

    class _SilentPopen(_original_popen):
        def __init__(self, *args, **kwargs):
            si = subprocess.STARTUPINFO()
            si.dwFlags    |= subprocess.STARTF_USESHOWWINDOW
            si.wShowWindow = subprocess.SW_HIDE
            kwargs.setdefault('startupinfo', si)
            super().__init__(*args, **kwargs)

    subprocess.Popen = _SilentPopen
