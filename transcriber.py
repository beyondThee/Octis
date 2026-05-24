"""
transcriber.py
===============
Uses local Whisper to convert audio chunks into text.
Whisper runs fully on your computer — no internet needed, completely free.
"""

import whisper


class Transcriber:
    def __init__(self, model_size="base"):
        """
        Loads the Whisper model once when the app starts.

        model_size options (trade-off between speed and accuracy):
          "tiny"   — fastest, least accurate  (~1GB RAM)
          "base"   — good balance             (~1GB RAM)  ← recommended for most laptops
          "small"  — more accurate, slower    (~2GB RAM)
          "medium" — best accuracy, slow      (~5GB RAM)
          "large"  — most accurate, very slow (~10GB RAM)

        The first time you run this, Whisper will download the model (~150MB for base).
        After that it's cached and loads instantly.
        """
        print(f"   Loading Whisper '{model_size}' model... ", end="", flush=True)
        self.model = whisper.load_model(model_size)
        print("ready!")

    def transcribe(self, audio_file_path):
        """
        Takes a path to a WAV audio file and returns the transcribed text as a string.

        audio_file_path: path to the .wav file to transcribe
        returns: string of transcribed words
        """
        result = self.model.transcribe(
            audio_file_path,
            fp16=False,       # fp16=False avoids warnings on CPUs that don't support it
            language="en"     # Change this if lectures are in another language
        )
        return result["text"].strip()
