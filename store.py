"""
store.py — local persistence for Quick Notes.

Everything lives under Documents/Octis/ as JSON. Files are written
atomically (temp file + rename) so a crash or power loss mid-write
can never leave a half-written file behind.

Files
-----
classes.json        the student's classes (name, colour, meeting pattern)
card_progress.json  per-card mastery state, keyed by lecture folder
cram_cache.json     generated cram question pools, keyed by class

lecture_history.json is owned by app.py and only extended here.
"""

import json
import os
import tempfile
import uuid
from datetime import datetime

DATA_DIR = os.path.join(os.path.expanduser("~"), "Documents", "Octis")
os.makedirs(DATA_DIR, exist_ok=True)

CLASSES_FILE  = os.path.join(DATA_DIR, "classes.json")
PROGRESS_FILE = os.path.join(DATA_DIR, "card_progress.json")
CRAM_FILE     = os.path.join(DATA_DIR, "cram_cache.json")

# Assigned in order as classes are created. Chosen to stay distinguishable
# under the common colour-vision deficiencies.
CLASS_COLORS = [
    "#4C72D9",  # blue
    "#D9822B",  # orange
    "#2E9E7C",  # green
    "#9B5DE5",  # purple
    "#C1476B",  # rose
    "#5BA3C7",  # cyan
]


# ── low-level helpers ──────────────────────────────────────────

def _load(path, default):
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        # Corrupt or unreadable — fall back rather than crashing the app.
        return default


def _save(path, data):
    """
    Atomic write: build the new file beside the real one, then rename.
    os.replace is atomic on Windows and POSIX, so readers never see a
    partially written file.
    """
    directory = os.path.dirname(path)
    fd, tmp = tempfile.mkstemp(dir=directory, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except Exception:
            pass
        raise


# ── classes ────────────────────────────────────────────────────

def load_classes(email=""):
    """All classes belonging to one account."""
    everything = _load(CLASSES_FILE, [])
    email = (email or "").strip().lower()
    if not email:
        return []
    return [c for c in everything if (c.get("email") or "").lower() == email]


def create_class(email, name, days=None, times=None):
    """
    Add a class. Colour is auto-assigned from the palette, reusing the
    first colour not already taken by this account.
    """
    everything = _load(CLASSES_FILE, [])
    mine       = load_classes(email)

    used   = {c.get("color") for c in mine}
    colour = next((c for c in CLASS_COLORS if c not in used), CLASS_COLORS[0])

    entry = {
        "id":         uuid.uuid4().hex[:12],
        "email":      (email or "").strip().lower(),
        "name":       name.strip(),
        "color":      colour,
        # Meeting pattern. The student may type these in, but recordings
        # are the source of truth once a pattern emerges.
        "days":       days  or [],
        "times":      times or [],
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    everything.append(entry)
    _save(CLASSES_FILE, everything)
    return entry


def update_class(email, class_id, **fields):
    """Rename, recolour, or adjust the meeting pattern of one class."""
    everything = _load(CLASSES_FILE, [])
    email = (email or "").strip().lower()
    for c in everything:
        if c.get("id") == class_id and (c.get("email") or "").lower() == email:
            for k, v in fields.items():
                if k in {"name", "color", "days", "times"} and v is not None:
                    c[k] = v
            _save(CLASSES_FILE, everything)
            return c
    return None


def delete_class(email, class_id):
    """
    Remove a class. Lectures are NOT deleted — app.py clears their
    class_id so they become unassigned rather than disappearing.
    """
    everything = _load(CLASSES_FILE, [])
    email = (email or "").strip().lower()
    kept = [c for c in everything
            if not (c.get("id") == class_id and (c.get("email") or "").lower() == email)]
    if len(kept) != len(everything):
        _save(CLASSES_FILE, kept)
        return True
    return False


def merge_classes(email, keep_id, absorb_id):
    """
    Fold one class into another. Returns True if the absorbed class was
    removed; the caller is responsible for repointing its lectures.
    """
    if keep_id == absorb_id:
        return False
    mine = {c["id"] for c in load_classes(email)}
    if keep_id not in mine or absorb_id not in mine:
        return False
    return delete_class(email, absorb_id)


# ── card progress ──────────────────────────────────────────────
#
# Keyed by lecture folder, then by a stable card key (the question
# text). Storing by question text rather than index means progress
# survives cards being added, removed, or reordered.

def load_progress(folder):
    return _load(PROGRESS_FILE, {}).get(folder, {})


def record_answer(folder, card_key, correct, confident):
    """
    Update one card's mastery after an answer.

    A card counts as mastered only after two successful AND confident
    recalls — one correct answer is the minimum, not the target, and
    fast-but-unsure clicks shouldn't retire a card.
    """
    everything = _load(PROGRESS_FILE, {})
    lecture    = everything.setdefault(folder, {})
    card       = lecture.setdefault(card_key, {"successes": 0, "attempts": 0})

    card["attempts"] = card.get("attempts", 0) + 1
    if correct and confident:
        card["successes"] = card.get("successes", 0) + 1
    elif not correct:
        card["successes"] = 0          # a miss resets the streak

    card["mastered"] = card["successes"] >= 2
    card["last_seen"] = datetime.now().isoformat(timespec="seconds")

    _save(PROGRESS_FILE, everything)
    return card


def reset_progress(folder):
    everything = _load(PROGRESS_FILE, {})
    if folder in everything:
        del everything[folder]
        _save(PROGRESS_FILE, everything)


# ── cram cache ─────────────────────────────────────────────────

def load_cram(class_id):
    """
    Returns {"questions": [...], "lectures": [folder, ...]} or None.
    'lectures' records which lectures the pool was built from, so new
    recordings can be topped up without regenerating everything.
    """
    return _load(CRAM_FILE, {}).get(class_id)


def save_cram(class_id, questions, lecture_folders):
    everything = _load(CRAM_FILE, {})
    everything[class_id] = {
        "questions":  questions,
        "lectures":   lecture_folders,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    }
    _save(CRAM_FILE, everything)


def merge_cram(class_id, new_questions, new_folders):
    """Add questions for newly recorded lectures without a full rebuild."""
    existing = load_cram(class_id)
    if not existing:
        save_cram(class_id, new_questions, new_folders)
        return

    questions = existing.get("questions", []) + new_questions
    folders   = list(dict.fromkeys(existing.get("lectures", []) + new_folders))
    save_cram(class_id, questions, folders)
