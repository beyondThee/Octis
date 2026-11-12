"""
file_import.py
===============
Turns an uploaded file into plain text for Quick Notes.

  - Slides and documents (.pptx, .docx, .pdf, .txt, .md): the text is
    pulled out right here on the student's computer. Only text is ever
    sent to the AI server.
  - Audio and video (.mp3, .wav, .m4a, ...): transcribed by the local
    Whisper model, a few minutes at a time, so the app can show progress.
"""

import os

DOC_TYPES   = {".pptx": "slides", ".docx": "document", ".pdf": "PDF",
               ".txt": "notes", ".md": "notes"}
AUDIO_TYPES = {".mp3", ".wav", ".m4a", ".aac", ".ogg", ".oga", ".opus",
               ".flac", ".wma", ".webm", ".mp4", ".mov", ".mkv"}

# Old Office formats need Microsoft's own libraries to read, so we ask
# the student to re-save them instead of guessing.
OLD_TYPES = {
    ".ppt": "This is an old PowerPoint file (.ppt). Open it in PowerPoint, "
            "choose File > Save As > PowerPoint Presentation (.pptx), then upload that.",
    ".doc": "This is an old Word file (.doc). Open it in Word, choose "
            "File > Save As > Word Document (.docx), then upload that.",
}

ALL_TYPES = sorted(set(DOC_TYPES) | AUDIO_TYPES)

CHUNK_SECONDS = 5 * 60          # transcribe audio 5 minutes at a time
SAMPLE_RATE   = 16000           # what Whisper expects


class ImportError_(Exception):
    """A problem with the file that the student can fix. Message is shown as-is."""


def file_kind(filename):
    """Returns 'audio', 'document', or raises ImportError_ with a friendly message."""
    ext = os.path.splitext(filename or "")[1].lower()
    if ext in AUDIO_TYPES:
        return "audio"
    if ext in DOC_TYPES:
        return "document"
    if ext in OLD_TYPES:
        raise ImportError_(OLD_TYPES[ext])
    raise ImportError_(
        "Quick Notes can't read that kind of file yet. Try PowerPoint (.pptx), "
        "Word (.docx), PDF, a text file, or an audio file like .mp3 or .m4a."
    )


def doc_label(filename):
    """Short word for the prompt, e.g. 'slides' or 'PDF'."""
    return DOC_TYPES.get(os.path.splitext(filename)[1].lower(), "document")


# ── Documents ──────────────────────────────────────────────────

def extract_text(path, filename=None):
    """Pulls the readable text out of a .pptx, .docx, .pdf, .txt or .md file."""
    ext = os.path.splitext(filename or path)[1].lower()
    try:
        if ext == ".pptx":
            text = _pptx_text(path)
        elif ext == ".docx":
            text = _docx_text(path)
        elif ext == ".pdf":
            text = _pdf_text(path)
        elif ext in (".txt", ".md"):
            text = _plain_text(path)
        else:
            file_kind(filename or path)        # raises the friendly message
            text = ""
    except ImportError_:
        raise
    except Exception as e:
        raise ImportError_(
            "Quick Notes couldn't open that file. It may be damaged or "
            f"password protected. ({type(e).__name__})"
        )

    text = _tidy(text)
    if len(text.split()) < 20:
        if ext == ".pdf":
            raise ImportError_(
                "This PDF has almost no text Quick Notes can read. It's probably "
                "a scan or photos of pages. Try the original slides or document instead."
            )
        raise ImportError_("That file has almost no text in it to make notes from.")
    return text


def _pptx_text(path):
    from pptx import Presentation
    prs   = Presentation(path)
    parts = []
    for num, slide in enumerate(prs.slides, start=1):
        lines = []
        for shape in slide.shapes:
            lines.extend(_shape_lines(shape))
        # Speaker notes often hold the real explanation
        if slide.has_notes_slide:
            notes = slide.notes_slide.notes_text_frame
            if notes is not None and notes.text.strip():
                lines.append("Speaker notes: " + notes.text.strip())
        if lines:
            parts.append(f"--- Slide {num} ---\n" + "\n".join(lines))
    return "\n\n".join(parts)


def _shape_lines(shape):
    lines = []
    if getattr(shape, "shape_type", None) == 6:          # a group of shapes
        for sub in shape.shapes:
            lines.extend(_shape_lines(sub))
        return lines
    if getattr(shape, "has_text_frame", False) and shape.text_frame.text.strip():
        lines.append(shape.text_frame.text.strip())
    if getattr(shape, "has_table", False):
        for row in shape.table.rows:
            cells = [c.text.strip() for c in row.cells]
            if any(cells):
                lines.append(" | ".join(cells))
    return lines


def _docx_text(path):
    import docx
    d     = docx.Document(path)
    parts = [p.text for p in d.paragraphs if p.text.strip()]
    for table in d.tables:
        for row in table.rows:
            cells = [c.text.strip() for c in row.cells]
            if any(cells):
                parts.append(" | ".join(cells))
    return "\n".join(parts)


def _pdf_text(path):
    from pypdf import PdfReader
    reader = PdfReader(path)
    if reader.is_encrypted:
        try:
            reader.decrypt("")
        except Exception:
            raise ImportError_("This PDF is password protected. Remove the password and try again.")
    return "\n\n".join((page.extract_text() or "") for page in reader.pages)


def _plain_text(path):
    with open(path, "rb") as f:
        raw = f.read()
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="ignore")


def _tidy(text):
    """Drops empty lines and stray spaces so page counts stay fair."""
    lines = [" ".join(line.split()) for line in (text or "").splitlines()]
    out, blank = [], False
    for line in lines:
        if line:
            out.append(line)
            blank = False
        elif not blank:
            out.append("")
            blank = True
    return "\n".join(out).strip()


# ── Audio ──────────────────────────────────────────────────────

def transcribe_audio(path, whisper_model, on_progress=None):
    """
    Transcribes an audio or video file with the local Whisper model.

    whisper_model: the already-loaded whisper model (Transcriber().model)
    on_progress:   optional function(done_minutes, total_minutes)
    Returns (transcript_text, duration_minutes).
    """
    import whisper
    try:
        audio = whisper.load_audio(path)            # uses the bundled ffmpeg
    except Exception:
        raise ImportError_(
            "Quick Notes couldn't play that audio file. It may be damaged, "
            "or in a format ffmpeg can't read."
        )

    total_secs = len(audio) / SAMPLE_RATE
    if total_secs < 5:
        raise ImportError_("That audio file is too short to make notes from.")
    total_mins = max(1, round(total_secs / 60))

    step  = CHUNK_SECONDS * SAMPLE_RATE
    parts = []
    for start in range(0, len(audio), step):
        if on_progress:
            on_progress(round(start / SAMPLE_RATE / 60), total_mins)
        chunk  = audio[start:start + step]
        result = whisper_model.transcribe(chunk, fp16=False, language="en")
        text   = result["text"].strip()
        if text:
            parts.append(text)
    if on_progress:
        on_progress(total_mins, total_mins)

    transcript = " ".join(parts).strip()
    if len(transcript.split()) < 5:
        raise ImportError_("Quick Notes couldn't hear any speech in that audio file.")
    return transcript, total_mins
