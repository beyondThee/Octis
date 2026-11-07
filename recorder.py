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
    def __init__(self, sample_rate=16000, base_model=None):
        self.sample_rate = sample_rate
        self.stop_flag   = threading.Event()
        # Reuse the base model the app already loaded at startup. Loading a
        # second copy here, plus the small model, ran low-RAM laptops out of
        # memory and the recording thread died with no message.
        self._base       = base_model
        self._small      = None
        # Loudest chunk seen this session. Lets the app tell "the mic sent
        # silence" apart from "the mic heard sound but Whisper found no words".
        self.peak_level  = 0.0
        self._input      = None   # (device, rate, channels, name, api)

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

    # Below this peak a stream is "dead": real mics, even in a quiet room,
    # have a noise floor well above it. Some Intel SST / Realtek mic arrays
    # hand MME (PortAudio's default on Windows) exact digital silence while
    # WASAPI gets the real signal, which looked like "no speech".
    DEAD_PEAK = 0.0003

    def _candidate_inputs(self):
        """Default input device of each Windows audio API, best first:
        WASAPI, then MME (the old default), then DirectSound."""
        order = ["Windows WASAPI", "MME", "Windows DirectSound"]
        found = []
        try:
            apis = sd.query_hostapis()
        except Exception as e:
            _log(f"Host API query failed: {e}")
            apis = []
        for name in order:
            for api in apis:
                idx = api.get("default_input_device", -1)
                if api.get("name") == name and idx is not None and idx >= 0:
                    found.append(idx)
        if not found:
            found.append(None)  # whatever PortAudio considers default
        return found

    def _open_info(self, device):
        info = sd.query_devices(device, kind='input') if device is None \
            else sd.query_devices(device)
        try:
            api = sd.query_hostapis(info['hostapi'])['name']
        except Exception:
            api = "?"
        rate = int(info['default_samplerate'])
        ch   = max(1, min(int(info['max_input_channels']), 8))
        return info, api, rate, ch

    def _capture(self, device, rate, channels, seconds):
        """Record and return the loudest channel as a flat float32 array.
        On mic arrays some channels can be silent, so averaging them all
        (or taking channel 1) can lose the voice."""
        frames = int(rate * seconds)
        data = sd.rec(frames, samplerate=rate, channels=channels,
                      dtype='float32', device=device)
        for _ in range(int(seconds * 10)):
            if self.stop_flag.is_set():
                break
            sd.sleep(100)
        sd.stop()
        if data.ndim == 1 or data.shape[1] == 1:
            return data.reshape(-1)
        loudest = int(np.argmax(np.sqrt(np.mean(data ** 2, axis=0))))
        return data[:, loudest].copy()

    def _choose_input(self):
        """Probe each candidate for half a second and keep the first one
        that delivers a live signal. Logged so debug.log shows the choice."""
        first_ok = None
        for dev in self._candidate_inputs():
            try:
                info, api, rate, ch = self._open_info(dev)
                probe = self._capture(dev, rate, ch, 0.5)
                peak  = float(np.max(np.abs(probe))) if probe.size else 0.0
                _log(f"Probe: {info['name']} | {api} | {rate} Hz | {ch} ch | "
                     f"peak={peak:.5f}")
                if first_ok is None:
                    first_ok = (dev, rate, ch, info['name'], api)
                if peak >= self.DEAD_PEAK:
                    return (dev, rate, ch, info['name'], api)
            except Exception as e:
                _log(f"Probe failed on device {dev}: {e!r}")
        return first_ok

    def _record_chunk(self, chunk_seconds):
        """
        Record from the chosen input at its native rate, then resample to
        16000 Hz for Whisper. Re-probes if the device goes silent or fails.
        """
        if self._input is None:
            self._input = self._choose_input()
            if self._input:
                dev, rate, ch, name, api = self._input
                _log(f"Mic: {name} | {api} | {rate} Hz | {ch} ch")

        audio_flat, native_rate = None, self.sample_rate
        if self._input:
            dev, native_rate, ch = self._input[:3]
            try:
                audio_flat = self._capture(dev, native_rate, ch, chunk_seconds)
            except Exception as e:
                _log(f"Record failed on {self._input[3]} ({self._input[4]}): {e!r}")
                self._input = None  # pick again next chunk

        if audio_flat is None:
            # Last resort: PortAudio default device, mono, 16 kHz
            try:
                audio_flat  = self._capture(None, self.sample_rate, 1, chunk_seconds)
                native_rate = self.sample_rate
            except Exception as e2:
                _log(f"Record fallback failed: {e2!r}")
                return np.zeros(self.sample_rate * chunk_seconds, dtype=np.float32)

        # A whole chunk of digital silence means this path is dead (e.g. the
        # driver stopped feeding it): choose again for the next chunk.
        if audio_flat.size and float(np.max(np.abs(audio_flat))) < self.DEAD_PEAK:
            self._input = None

        # Resample to 16000 Hz using numpy (no scipy needed)
        return _resample(audio_flat, native_rate, self.sample_rate)

    def _transcribe(self, model, audio_data):
        try:
            # Skip near-silent audio without burning CPU on it
            rms = float(np.sqrt(np.mean(audio_data ** 2)))
            peak = float(np.max(np.abs(audio_data))) if audio_data.size else 0.0
            self.peak_level = max(self.peak_level, peak)
            # Levels only — never lecture content
            _log(f"Audio level: rms={rms:.5f} peak={peak:.4f}")
            if rms < 0.0001:
                return ""

            # Pass numpy array directly to Whisper — bypasses ffmpeg entirely
            audio_input = audio_data.astype(np.float32)

            result = model.transcribe(
                audio_input,
                fp16=False,
                language="en",
                no_speech_threshold=0.3,
                logprob_threshold=-2.0,
            )
            return result["text"].strip()
        except Exception as e:
            # Errors only — never log lecture content
            _log(f"Transcribe error: {e}")
            return ""

    def record_in_chunks(self, chunk_seconds=30):
        """
        Generator yielding (pass_num, text, words) tuples.
          pass_num 1 — base model, 30s chunk, list of words for typing effect
          pass_num 2 — small model, 60s chunk, full corrected text
        """
        self.stop_flag.clear()
        self.peak_level = 0.0
        self._input     = None   # re-probe each recording (mic may have changed)

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
                    try:
                        model = self._get_small()
                    except Exception as e:
                        # Pass 2 is only a correction; pass 1 text stays.
                        _log(f"Small model load failed: {e!r}")
                        return
                    text = self._transcribe(model, audio)
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
