"""
note_generator.py
==================
Calls the Octis Railway server to generate notes, flashcards, summary and title.
The Anthropic API key lives on the server — never in this app.
"""

import requests

SERVER_URL  = "https://web-production-2b0e5.up.railway.app"
APP_SECRET  = "octis2026secretkey"   # must match APP_SECRET on Railway

HEADERS = {
    "Content-Type":   "application/json",
    "X-Octis-Secret": APP_SECRET,
}


class NoteGenerator:
    def generate(self, transcript):
        """
        Sends the transcript to the Octis server and returns:
          - title
          - notes
          - flashcards
          - summary
        """
        response = requests.post(
            f"{SERVER_URL}/generate",
            headers=HEADERS,
            json={"transcript": transcript},
            timeout=120,   # 2 minute timeout for long lectures
        )
        response.raise_for_status()
        return response.json()

    def generate_with_textbook(self, transcript, textbook_text):
        """
        Sends transcript + textbook content to the server.
        Returns enhanced notes and flashcards only.
        """
        response = requests.post(
            f"{SERVER_URL}/textbook",
            headers=HEADERS,
            json={
                "transcript": transcript,
                "textbook":   textbook_text,
            },
            timeout=120,
        )
        response.raise_for_status()
        return response.json()
