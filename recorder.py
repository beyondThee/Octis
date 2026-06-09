"""
recorder.py
============
Two-pass transcription:
  Pass 1 — every 30s using base model  → words type smoothly onto screen
  Pass 2 — every 60s using small model → silent background correction

Records at the device's native rate then resamples to 16000 Hz using
numpy only (no scipy dependency needed).
"""

import sounddevice as sd
import soundfile as sf
import tempfile
import threading
import os
import numpy as np


def _resample(audio, from_rate, to_rate):
    """Resample audio using numpy linear interpolation. No scipy needed."""
    if from_rate == to_rate:
        return audio
    target_length = int(len(audio) * to_rate / from_rate)
    resampled = np.interp(
        np.linspace(0, len(audio) - 1, target_length),
        np.arange(len(audio)),
        audio
    )
    return resampled.astype(np.float32)


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
        """
        Record audio at the device's native sample rate,
        then resample to 16000 Hz for Whisper.
        """
        # Get native sample rate of default input device
        try:
            device_info = sd.query_devices(kind='input')
            native_rate = int(device_info['default_samplerate'])
            print(f"Recording device: {device_info['name']}, rate: {native_rate}")
        except Exception as e:
            print(f"Device query failed: {e}")
            native_rate = self.sample_rate

        frames = int(native_rate * chunk_seconds)

        try:
            audio_data = sd.rec(frames, samplerate=native_rate,
                                channels=1, dtype='float32', device=None)

            for _ in range(chunk_seconds * 10):
                if self.stop_flag.is_set():
                    sd.stop()
                    break
                sd.sleep(100)

            sd.stop()
            audio_flat = audio_data.flatten()

        except Exception as e:
            # Fallback: try recording at 16000 Hz directly
            try:
                frames     = int(self.sample_rate * chunk_seconds)
                audio_data = sd.rec(frames, samplerate=self.sample_rate,
                                    channels=1, dtype='float32')
                for _ in range(chunk_seconds * 10):
                    if self.stop_flag.is_set():
                        sd.stop()
                        break
                    sd.sleep(100)
                sd.stop()
                audio_flat  = audio_data.flatten()
                native_rate = self.sample_rate
            except Exception:
                return np.zeros(self.sample_rate * chunk_seconds, dtype=np.float32)

        # Resample to 16000 Hz using numpy (no scipy needed)
        return _resample(audio_flat, native_rate, self.sample_rate)

    def _transcribe(self, model, audio_data):
        tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        try:
            sf.write(tmp.name, audio_data, self.sample_rate)

            # Check if audio has any signal at all
            rms = float(np.sqrt(np.mean(audio_data ** 2)))
            print(f"Audio RMS level: {rms:.6f}")

            if rms < 0.0001:
                print("WARNING: Audio appears to be silence or near-silence")
                return ""

            result = model.transcribe(
                tmp.name,
                fp16=False,
                language="en",
                no_speech_threshold=0.3,   # default is 0.6 — lower = more sensitive
                logprob_threshold=-2.0,    # default is -1.0 — more lenient
            )
            text = result["text"].strip()
            print(f"Whisper result: '{text[:100]}'")
            return text
        except Exception as e:
            print(f"Transcribe error: {e}")
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
            # Record chunk and resample to 16000 Hz
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
                combined         = np.concatenate(audio_buffer_60s)
                gid              = group_60s
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