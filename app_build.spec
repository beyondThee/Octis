# app_build.spec
# ─────────────────────────────────────────────────────────────
# Builds just the Python Flask backend into app.exe
# Electron wraps this and calls it as a subprocess
# ─────────────────────────────────────────────────────────────

from PyInstaller.utils.hooks import collect_data_files

block_cipher = None

FFMPEG_BIN  = r'C:\Users\MJ\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-8.1-full_build\bin\ffmpeg.exe'
FFPROBE_BIN = r'C:\Users\MJ\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-8.1-full_build\bin\ffprobe.exe'

whisper_datas = collect_data_files('whisper')

a = Analysis(
    ['app.py'],
    pathex=[],
    binaries=[
        (FFMPEG_BIN,  '.'),
        (FFPROBE_BIN, '.'),
    ],
    datas=[
        ('templates', 'templates'),
        ('static',    'static'),
        ('config.py', '.'),
        *whisper_datas,
    ],
    hiddenimports=[
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
    runtime_hooks=['hook_ffmpeg.py'],
    excludes=['webview'],   # no longer needed
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='app',
    debug=False,
    strip=False,
    upx=True,
    console=False,
    windowsHide=True,   # never show a window
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='app',
)
