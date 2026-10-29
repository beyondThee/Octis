# hook_macos.py
# ─────────────────────────────────────────────────────────────
# PyInstaller runtime hook for the Mac build — runs before app.py.
#
# The frozen Python looks for SSL certificates at the path they had
# on the build machine, which doesn't exist on a student's Mac. Then
# the first-launch Whisper model download fails with
# CERTIFICATE_VERIFY_FAILED. Point it at certifi's bundled copy.
# ─────────────────────────────────────────────────────────────

import os
import sys

if getattr(sys, 'frozen', False):
    try:
        import certifi
        os.environ.setdefault('SSL_CERT_FILE', certifi.where())
        os.environ.setdefault('REQUESTS_CA_BUNDLE', certifi.where())
    except Exception:
        pass
