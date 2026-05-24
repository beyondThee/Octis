# study_companion.spec
# ─────────────────────────────────────────────────────────────
# PyInstaller spec — bundles ffmpeg.exe so students need
# nothing extra installed. Just double-click and go.
#
# BEFORE BUILDING:
#   Make sure ffmpeg.exe and ffprobe.exe exist at C:\ffmpeg\bin\
#   (You already installed ffmpeg earlier via winget)
# ─────────────────────────────────────────────────────────────

from PyInstaller.utils.hooks import collect_data_files

block_cipher = None

# ── Paths ──────────────────────────────────────────────────────
FFMPEG_BIN  = r'C:\Users\MJ\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-8.1-full_build\bin\ffmpeg.exe'
FFPROBE_BIN = r'C:\Users\MJ\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-8.1-full_build\bin\ffprobe.exe'


# ── Collect data files ─────────────────────────────────────────
whisper_datas = collect_data_files('whisper')
webview_datas = collect_data_files('webview')

a = Analysis(
    ['app.py'],
    pathex=[],
    binaries=[
        (FFMPEG_BIN,  '.'),   # bundle ffmpeg.exe into root of package
        (FFPROBE_BIN, '.'),   # bundle ffprobe.exe into root of package
    ],
    datas=[
        ('templates', 'templates'),
        ('config.py', '.'),
        *whisper_datas,
        *webview_datas,
    ],
    hiddenimports=[
        'webview',
        'webview.platforms.winforms',
        'clr',
        'flask',
        'anthropic',
        'whisper',
        'sounddevice',
        'soundfile',
        'numpy',
        'torch',
        'tiktoken',
        'tiktoken_ext',
        'tiktoken_ext.openai_public',
    ],
    hookspath=[],
    runtime_hooks=['hook_ffmpeg.py'],   # runs before app starts
    excludes=[],
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='StudyCompanion',
    debug=False,
    strip=False,
    upx=True,
    console=False,   # no black command prompt window
    icon=None,       # swap in icon.ico here if you have one
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='StudyCompanion',
)
