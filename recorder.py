"""
recorder.py
============
Two-pass transcription:
  Pass 1 — every 30s using base model  → words type smoothly onto screen
  Pass 2 — every 60s using small model → silent background correction

Uses the system default input device and auto-detects sample rate.
"""

import sounddevice as sd
import soundfile as sf
import tempfile
import threading
import os
import numpy as np


class Recorder:
    def __init__(self, sample_rate=16000):
        self.sample_rate = sample_rate
        self.stop_flag   = threading.Event()
        self._base       = None
        self._small      = None

    def _get_base(self):
        if not self._base:
            import whisper
            self._base = whisper.load_model("base")
        return self._base

    def _get_small(self):
        if not self._small:
            import whisper
            self._small = whisper.load_model("small")
        return self._small

    def _record_chunk(self, chunk_seconds):
        """Record using the system default input device at its native sample rate."""
        try:
            device_info = sd.query_devices(kind='input')
            sample_rate = int(device_info['default_samplerate'])
        except Exception:
            sample_rate = self.sample_rate

        frames     = int(sample_rate * chunk_seconds)
        audio_data = sd.rec(frames, samplerate=sample_rate,
                            channels=1, dtype='float32', device=None)

        for _ in range(chunk_seconds * 10):
            if self.stop_flag.is_set():
                sd.stop()
                break
            sd.sleep(100)

        sd.stop()
        audio_flat = audio_data.flatten()

        # Resample to 16000 Hz if needed for Whisper
        if sample_rate != self.sample_rate:
            try:
                from scipy import signal
                num_samples = int(len(audio_flat) * self.sample_rate / sample_rate)
                audio_flat  = signal.resample(audio_flat, num_samples)
            except ImportError:
                pass  # if scipy not available, use as-is

        return audio_flat

    def _transcribe(self, model, audio_data):
        tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        try:
            sf.write(tmp.name, audio_data, self.sample_rate)
            result = model.transcribe(tmp.name, fp16=False, language="en")
            return result["text"].strip()
        except Exception:
            return ""
        finally:
            try:
                os.unlink(tmp.name)
            except Exception:
                pass

    def record_in_chunks(self, chunk_seconds=30):
        """
        Generator yielding (pass_num, text, words) tuples.
          pass_num 1 — base model, 30s chunk, list of words for typing effect
          pass_num 2 — small model, 60s chunk, full corrected text
        """
        self.stop_flag.clear()

        audio_buffer_60s = []
        group_60s        = 0
        revision_queue   = []

        while not self.stop_flag.is_set():
            # Record 30 second chunk using system default mic
            audio_flat = self._record_chunk(chunk_seconds)

            # Pass 1: base model transcription
            text = self._transcribe(self._get_base(), audio_flat)
            if text.strip():
                words = text.split()
                yield (1, text, words)

            # Accumulate for 60s pass
            audio_buffer_60s.append(audio_flat)

            # Pass 2: every 60s, small model in background
            if len(audio_buffer_60s) >= 2:
                combined = np.concatenate(audio_buffer_60s)
                gid      = group_60s
                group_60s       += 1
                audio_buffer_60s = []

                def do_pass2(audio=combined, g=gid):
                    text = self._transcribe(self._get_small(), audio)
                    if text.strip():
                        revision_queue.append((2, text, g))

                threading.Thread(target=do_pass2, daemon=True).start()

            # Yield any ready pass 2 results
            while revision_queue:
                item = revision_queue.pop(0)
                yield item

        # Flush remaining audio through base model
        if audio_buffer_60s:
            combined = np.concatenate(audio_buffer_60s)
            text     = self._transcribe(self._get_base(), combined)
            if text.strip():
                yield (1, text, text.split())