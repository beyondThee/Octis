"""
output_saver.py
================
Saves lecture materials to a dedicated folder in the user's home directory.
This folder survives app updates, reinstalls, and uninstalls completely.

Windows: C:\Users\YourName\Documents\Octis\
Mac:     /Users/YourName/Documents/Octis/
"""

import os
from datetime import datetime


def get_user_data_dir():
    """
    Returns the path to the Octis data folder in the user's Documents.
    Creates it if it doesn't exist.
    This location is completely separate from the app installation
    and will never be touched by updates or uninstalls.
    """
    documents = os.path.join(os.path.expanduser("~"), "Documents")
    octis_dir = os.path.join(documents, "Octis")
    os.makedirs(octis_dir, exist_ok=True)
    return octis_dir


class OutputSaver:
    def __init__(self):
        self.base_folder = os.path.join(get_user_data_dir(), "Lectures")
        os.makedirs(self.base_folder, exist_ok=True)

    def save(self, results, transcript):
        timestamp     = datetime.now().strftime("%Y-%m-%d_%H-%M")
        output_folder = os.path.join(self.base_folder, f"lecture_{timestamp}")
        os.makedirs(output_folder, exist_ok=True)

        self._write_file(output_folder, "transcript.txt",
            "FULL LECTURE TRANSCRIPT\n" + "=" * 40 + "\n\n" + transcript)

        self._write_file(output_folder, "notes.txt",
            "LECTURE NOTES\n" + "=" * 40 + "\n\n" + results.get("notes", "No notes generated."))

        self._write_file(output_folder, "flashcards.txt",
            "FLASHCARDS\n" + "=" * 40 + "\n\n" + results.get("flashcards", "No flashcards generated."))

        self._write_file(output_folder, "summary.txt",
            "LECTURE SUMMARY\n" + "=" * 40 + "\n\n" + results.get("summary", "No summary generated."))

        return output_folder

    def _write_file(self, folder, filename, content):
        filepath = os.path.join(folder, filename)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)
