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
            return True, data.get("token"), {
                "email":         email,
                "plan":          data.get("plan", "trial"),
                "trial_ends_at": data.get("trial_ends_at"),
            }
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
    try:
        response = requests.post(
            f"{WEBSITE_URL}/api/auth/verify",
            json={"email": email},
            headers={"Authorization": f"Bearer {jwt_token}"},
            timeout=10,
        )
        data = response.json()
        if response.status_code == 200 and data.get("valid"):
            return True, {
                "email":         email,
                "plan":          data.get("plan", "trial"),
                "trial_ends_at": data.get("trial_ends_at"),
                "trial_ended":   data.get("trial_ended", False),
            }
        return False, data.get("message", "Session expired")
    except Exception:
        # If server unreachable allow offline use with saved token
        return True, {"email": email, "plan": "unknown", "trial_ended": False}


class NoteGenerator:
    def __init__(self, jwt_token=""):
        self.jwt_token = jwt_token

    def generate(self, transcript):
        response = requests.post(
            f"{SERVER_URL}/generate",
            headers=get_server_headers(self.jwt_token),
            json={"transcript": transcript},
            timeout=120,
        )
        response.raise_for_status()
        return response.json()

    def generate_with_textbook(self, transcript, textbook_text):
        response = requests.post(
            f"{SERVER_URL}/textbook",
            headers=get_server_headers(self.jwt_token),
            json={"transcript": transcript, "textbook": textbook_text},
            timeout=120,
        )
        response.raise_for_status()
        return response.json()
