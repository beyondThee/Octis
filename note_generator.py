"""
note_generator.py
==================
Handles authentication against quicknotesai.com
and generates notes via the Railway server.
"""

import requests
from device_fingerprint import get_fingerprint

WEBSITE_URL = "https://quicknotesai.com"
SERVER_URL  = "https://web-production-2b0e5.up.railway.app"
APP_SECRET  = "octis2026secretkey"


def get_server_headers(jwt_token=""):
    return {
        "Content-Type":    "application/json",
        "X-Octis-Secret":  APP_SECRET,
        "X-Auth-Token":    jwt_token,
    }


def login(email, password):
    """
    Logs in with email and password against quicknotesai.com.
    Returns (True, token, account_info) or (False, error_message, None)
    """
    try:
        fingerprint = get_fingerprint()
        response = requests.post(
            f"{WEBSITE_URL}/api/auth/login",
            json={
                "email":              email,
                "password":           password,
                "device_fingerprint": fingerprint,
            },
            timeout=15,
        )
        data = response.json()
        if response.status_code == 200 and data.get("token"):
            plan        = data.get("plan", "trial")
            trial_ended = bool(data.get("trial_ended", False)) or plan == "expired"
            return True, data.get("token"), {
                "email":         email,
                "plan":          plan,
                "trial_ends_at": data.get("trial_ends_at"),
                "trial_ended":   trial_ended,
            }
        # No token issued — could be bad credentials OR an expired account
        if data.get("trial_ended"):
            return False, data.get("message", "Your access has ended."), {"trial_ended": True}
        return False, data.get("message", "Invalid email or password"), None
    except requests.exceptions.ConnectionError:
        return False, "Could not connect. Please check your internet connection.", None
    except Exception as e:
        return False, f"Login failed: {e}", None


def verify_token(jwt_token, email=""):
    """
    Silently verifies a saved JWT token on app startup.
    Returns (True, account_info) or (False, error_message)
    """
    import os as _os
    from datetime import datetime as _dt
    def _vlog(msg):
        try:
            d = _os.path.join(_os.path.expanduser("~"), "Documents", "Octis")
            _os.makedirs(d, exist_ok=True)
            with open(_os.path.join(d, "debug.log"), "a") as f:
                f.write(f"[{_dt.now().strftime('%H:%M:%S')}] verify: {msg}\n")
        except Exception:
            pass

    try:
        response = requests.post(
            f"{WEBSITE_URL}/api/auth/verify",
            json={"email": email},
            headers={"Authorization": f"Bearer {jwt_token}"},
            timeout=10,
        )
        data = response.json()
        _vlog(f"status={response.status_code} body={data}")

        if response.status_code == 200 and data.get("valid"):
            return True, {
                "email":         email,
                "plan":          data.get("plan", "trial"),
                "trial_ends_at": data.get("trial_ends_at"),
                "trial_ended":   data.get("trial_ended", False),
            }
        # Reached the server and it said NOT valid — block access.
        return False, {
            "message":     data.get("message", "Session expired"),
            "trial_ended": data.get("trial_ended", False),
        }

    except requests.exceptions.RequestException as e:
        # Only a genuine CONNECTION failure (offline / server down) grants
        # temporary offline access. A bad response is NOT a connection error
        # and must never fall here.
        _vlog(f"connection error (offline grace): {e}")
        return True, {"email": email, "plan": "unknown", "trial_ended": False}
    except Exception as e:
        # Any other error (bad JSON, unexpected shape) — fail CLOSED, block.
        _vlog(f"unexpected error (blocking): {e}")
        return False, {"message": "Could not verify session", "trial_ended": False}


class GenerateError(Exception):
    """Carries the server's reason code ('offline', 'access', or '') so
    the app can respond differently to each."""
    def __init__(self, message, reason=""):
        super().__init__(message)
        self.reason = reason


class NoteGenerator:
    def __init__(self, jwt_token=""):
        self.jwt_token = jwt_token

    def _handle(self, response):
        """Extract the server's error message instead of a generic HTTP error."""
        if response.status_code >= 400:
            reason = ""
            try:
                body   = response.json()
                detail = body.get("error", "")
                reason = body.get("reason", "")
            except Exception:
                detail = response.text[:200]
            raise GenerateError(detail or f"Server returned {response.status_code}", reason)
        return response.json()

    def generate(self, transcript):
        response = requests.post(
            f"{SERVER_URL}/generate",
            headers=get_server_headers(self.jwt_token),
            json={"transcript": transcript},
            timeout=120,
        )
        return self._handle(response)

    def generate_with_textbook(self, transcript, textbook_text):
        response = requests.post(
            f"{SERVER_URL}/textbook",
            headers=get_server_headers(self.jwt_token),
            json={"transcript": transcript, "textbook": textbook_text},
            timeout=120,
        )
        return self._handle(response)
