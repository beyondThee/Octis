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
import time
import os
import numpy as np
from datetime import datetime

# Debug log file in Documents/Octis
LOG_FILE = os.path.join(os.path.expanduser("~"), "Documents", "Octis", "debug.log")

def _log(msg):
    try:
        os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
        with open(LOG_FILE, "a") as f:
            f.write(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}\n")
    except Exception:
        pass


def _timed_words(result):
    """
    Pulls (start, end, word) out of a Whisper result. Uses per-word times
    when Whisper gave them, otherwise spreads each segment's words evenly
    across that segment so we still get rough timings.
    """
    out = []
    for seg in result.get("segments", []):
        words = seg.get("words")
        if words:
            for w in words:
                word = w.get("word", "").strip()
                if word:
                    out.append((float(w["start"]), float(w["end"]), word))
            continue
        parts = seg.get("text", "").split()
        if not parts:
            continue
        start, end = float(seg["start"]), float(seg["end"])
        step = (end - start) / len(parts)
        for i, word in enumerate(parts):
            out.append((start + i * step, start + (i + 1) * step, word))
    return out


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
        self._word_times_broken = False

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
        except Exception as e:
            _log(f"Device query failed: {e}")
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

    def _transcribe(self, model, audio_data, timed=False):
        """
        Returns the text. With timed=True returns (text, words) instead,
        where words is a list of (start_sec, end_sec, word) measured from
        the start of this audio. The live transcript uses those times to
        start a new paragraph when the speaker pauses.
        """
        empty = ("", []) if timed else ""
        try:
            # Skip near-silent audio without burning CPU on it
            rms = float(np.sqrt(np.mean(audio_data ** 2)))
            if rms < 0.0001:
                return empty

            # Pass numpy array directly to Whisper — bypasses ffmpeg entirely
            audio_input = audio_data.astype(np.float32)

            options = dict(
                fp16=False,
                language="en",
                no_speech_threshold=0.3,
                logprob_threshold=-2.0,
            )
            result = None
            if timed and not self._word_times_broken:
                try:
                    result = model.transcribe(audio_input, word_timestamps=True, **options)
                except Exception as e:
                    # Word timings need extra pieces (numba) that could be
                    # missing in a packaged build. Never lose the lecture
                    # over it: switch them off and transcribe normally.
                    # Paragraphs then use rougher per-sentence times.
                    _log(f"Word timestamps off: {e}")
                    self._word_times_broken = True
            if result is None:
                result = model.transcribe(audio_input, **options)
            text = result["text"].strip()
            if not timed:
                return text
            return text, _timed_words(result)
        except Exception as e:
            # Errors only — never log lecture content
            _log(f"Transcribe error: {e}")
            return empty

    def record_in_chunks(self, chunk_seconds=30):
        """
        Generator yielding tuples.
          pass 1 — (1, text, words, chunk_start, chunk_len, timed_words)
                   base model, 30s chunk. words is the plain word list,
                   chunk_start is the wall-clock time (time.time()) the
                   chunk began, chunk_len its length in seconds, and
                   timed_words a list of (start, end, word) inside the chunk.
          pass 2 — (2, text, group): small model, 60s chunk, corrected text
        """
        self.stop_flag.clear()

        audio_buffer_60s = []
        group_60s        = 0
        revision_queue   = []

        while not self.stop_flag.is_set():
            # Record chunk and resample to 16000 Hz
            chunk_start = time.time()
            audio_flat  = self._record_chunk(chunk_seconds)
            chunk_len   = len(audio_flat) / self.sample_rate

            # Pass 1: base model transcription
            text, timed = self._transcribe(self._get_base(), audio_flat, timed=True)
            if text.strip():
                words = text.split()
                yield (1, text, words, chunk_start, chunk_len, timed)

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
                yield (1, text, text.split(), None, 0, [])
