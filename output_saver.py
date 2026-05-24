"""
output_saver.py
================
Saves the transcript, notes, flashcards, and summary to a dated folder
so each lecture's materials are neatly organized.
"""

import os
from datetime import datetime


class OutputSaver:
    def __init__(self, base_folder="study_materials"):
        """
        base_folder: the root folder where all lecture materials are saved.
                     A new subfolder is created for each lecture automatically.
        """
        self.base_folder = base_folder

    def save(self, results, transcript):
        """
        Saves all study materials to a timestamped folder.

        results: dict with keys "notes", "flashcards", "summary"
        transcript: the full raw transcript string
        returns: path to the output folder
        """
        # Create a folder name based on the current date and time
        # e.g. "study_materials/2026-04-06_14-30"
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M")
        output_folder = os.path.join(self.base_folder, f"lecture_{timestamp}")
        os.makedirs(output_folder, exist_ok=True)

        # Save transcript
        self._write_file(
            output_folder,
            "transcript.txt",
            "FULL LECTURE TRANSCRIPT\n" + "=" * 40 + "\n\n" + transcript
        )

        # Save notes
        self._write_file(
            output_folder,
            "notes.txt",
            "LECTURE NOTES\n" + "=" * 40 + "\n\n" + results.get("notes", "No notes generated.")
        )

        # Save flashcards
        self._write_file(
            output_folder,
            "flashcards.txt",
            "FLASHCARDS\n" + "=" * 40 + "\n\n" + results.get("flashcards", "No flashcards generated.")
        )

        # Save summary
        self._write_file(
            output_folder,
            "summary.txt",
            "LECTURE SUMMARY\n" + "=" * 40 + "\n\n" + results.get("summary", "No summary generated.")
        )

        return output_folder

    def _write_file(self, folder, filename, content):
        """Helper to write a single text file."""
        filepath = os.path.join(folder, filename)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)
