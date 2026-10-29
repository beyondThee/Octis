# app_build_mac.spec
# ─────────────────────────────────────────────────────────────
# Mac version of app_build.spec. Builds the Flask backend into a
# plain `app` executable that Electron starts as a subprocess.
#
# Differences from Windows:
#   - No ffmpeg. The recorder hands audio to Whisper as numbers,
#     so ffmpeg is never called. (Homebrew's ffmpeg also wouldn't
#     run on students' Macs — it needs Homebrew's libraries.)
#   - No UPX. It breaks Apple code signing.
#   - hook_macos.py fixes SSL certificates for the Whisper download.
# ─────────────────────────────────────────────────────────────

from PyInstaller.utils.hooks import collect_data_files

block_cipher = None

whisper_datas = collect_data_files('whisper')
certifi_datas = collect_data_files('certifi')

a = Analysis(
    ['app.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('templates', 'templates'),
        ('static',    'static'),
        ('config.py', '.'),
        *whisper_datas,
        *certifi_datas,
    ],
    hiddenimports=[
        'flask',
        'requests',
        'certifi',
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
    runtime_hooks=['hook_macos.py'],
    excludes=['webview'],
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
    upx=False,
    console=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    name='app',
)
