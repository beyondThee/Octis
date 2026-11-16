"""
live_paragraphs.py
==================
Splits the live transcript into paragraphs while recording.

A new paragraph starts when the speaker goes quiet for PAUSE_SECONDS or
more. Each paragraph begins with a marker holding the lecture time, like
"12:30", so students can find the spot they zoned out.

The output goes into the typing queue that /api/words streams to the
screen. Words are plain strings. A paragraph start is a dict:
{"p": "12:30"}.
"""

PAUSE_SECONDS = 2.0

# Safety net: if a professor talks for ages with no 2-second pause, start
# a new paragraph at the next sentence end once a paragraph gets this long.
MAX_WORDS = 90


def format_clock(seconds):
    """65 -> '1:05', 3725 -> '1:02:05'."""
    seconds = max(0, int(seconds))
    h, rest = divmod(seconds, 3600)
    m, s = divmod(rest, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


class ParagraphSplitter:
    def __init__(self):
        self.reset()

    def reset(self):
        # Seconds of silence heard at the end of the last chunk. None means
        # nothing has been typed yet, so the next word opens a paragraph.
        self.trailing_silence = None
        self.words_in_paragraph = 0
        self.force_break = False
        self.last_word = ""
        self.last_time = 0.0

    def _marker(self, seconds):
        # Never let a paragraph time go backwards (can happen right after
        # a pause, when a chunk recorded during the pause comes in late).
        self.last_time = max(self.last_time, seconds)
        return {"p": format_clock(self.last_time)}

    def break_next(self):
        """Start a new paragraph at the next word (used after resume)."""
        self.force_break = True

    def add_chunk(self, chunk_offset, chunk_len, timed_words, plain_words=None):
        """
        chunk_offset: lecture time (seconds) where this chunk's audio starts
        chunk_len:    length of the chunk's audio in seconds
        timed_words:  [(start, end, word), ...] relative to the chunk start
        plain_words:  fallback word list if Whisper gave no timings

        Returns the list of queue items for this chunk.
        """
        out = []

        if not timed_words:
            # No timings: one paragraph per chunk is the best we can do.
            words = plain_words or []
            if words:
                out.append(self._marker(chunk_offset))
                out.extend(words)
                self.words_in_paragraph = len(words)
                self.last_word = words[-1]
                self.trailing_silence = 0.0
                self.force_break = False
            return out

        prev_end = None
        for start, end, word in timed_words:
            if prev_end is None:
                # First word of this chunk. Silence we actually heard =
                # quiet tail of the last chunk + quiet head of this one.
                # (Gaps while the computer was busy transcribing are not
                # counted: nobody heard them, so they aren't real pauses.)
                if self.trailing_silence is None:
                    gap = None
                else:
                    gap = self.trailing_silence + max(0.0, start)
            else:
                gap = start - prev_end

            long_paragraph = (
                self.words_in_paragraph >= MAX_WORDS
                and _ends_sentence(self.last_word)
            )
            if gap is None or gap >= PAUSE_SECONDS or self.force_break or long_paragraph:
                out.append(self._marker(chunk_offset + start))
                self.words_in_paragraph = 0
                self.force_break = False

            out.append(word)
            self.words_in_paragraph += 1
            self.last_word = word
            prev_end = end

        self.trailing_silence = max(0.0, chunk_len - prev_end)
        return out



def _ends_sentence(word):
    return word.rstrip('"\')').endswith((".", "?", "!"))
