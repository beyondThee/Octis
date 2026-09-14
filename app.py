"""
app.py
=======
Flask server — the new entry point for Study Companion.
Replaces ui.py and main.py.

Install:
  pip install flask

Run:
  python app.py

The app opens automatically in your default browser.
"""

import threading
import json
import random
import os
from datetime import datetime
from flask import Flask, render_template, jsonify, request, Response
from recorder import Recorder
from transcriber import Transcriber
import requests
from note_generator import NoteGenerator, login, verify_token, WEBSITE_URL
from output_saver import OutputSaver
import store

app = Flask(__name__, static_folder='static', static_url_path='/static')

# ── Data directory setup ───────────────────────────────────────
OCTIS_DATA_DIR = os.path.join(os.path.expanduser("~"), "Documents", "Octis")
os.makedirs(OCTIS_DATA_DIR, exist_ok=True)
HISTORY_FILE = os.path.join(OCTIS_DATA_DIR, "lecture_history.json")
LICENSE_FILE = os.path.join(OCTIS_DATA_DIR, "license.json")


def load_license():
    if os.path.exists(LICENSE_FILE):
        try:
            with open(LICENSE_FILE) as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_license(data):
    with open(LICENSE_FILE, "w") as f:
        json.dump(data, f)


def load_history():
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE) as f:
                return json.load(f)
        except Exception:
            return []
    return []


def save_history(h):
    with open(HISTORY_FILE, "w") as f:
        json.dump(h, f, indent=2)


def current_email():
    """
    The signed-in account. state["email"] is empty for a moment at
    startup while the session check runs in a background thread, so
    fall back to the saved session file rather than returning nothing.
    """
    email = (state.get("email") or "").strip().lower()
    if not email:
        email = (load_license().get("email") or "").strip().lower()
    return email


def load_user_history():
    """
    Return only the lectures belonging to the currently logged-in account,
    as (full_index, entry) pairs so callers can write back correctly.
    """
    history = load_history()
    email   = (state.get("email") or "").strip().lower()

    # The session check runs in a background thread on startup, so
    # state["email"] may not be populated yet when the page first loads.
    if not email:
        email = (load_license().get("email") or "").strip().lower()

    # No one signed in — show nothing rather than leaking recordings.
    if not email:
        return []

    # One-time migration: lectures made before accounts were scoped have
    # no "email". Claim them for the FIRST account that signs in after
    # updating, then never again — otherwise a brand new account could
    # take over someone else's recordings.
    marker = os.path.join(OCTIS_DATA_DIR, ".history_claimed")
    if not os.path.exists(marker):
        changed = False
        for entry in history:
            if not entry.get("email"):
                entry["email"] = email
                changed = True
        if changed:
            save_history(history)
        try:
            with open(marker, "w") as f:
                f.write(email)
        except Exception:
            pass

    return [
        (i, e) for i, e in enumerate(history)
        if (e.get("email") or "").strip().lower() == email
    ]


# ── App state ──────────────────────────────────────────────────
state = {
    "recording":    False,
    "paused":       False,
    "generating":   False,
    "transcript":   "",
    "status":       "",
    "results":      None,
    "recorder":     None,
    "transcriber":  None,
    "record_start": None,
    "licensed":     False,
    "trial_ended":  False,
    "jwt_token":    "",
    "email":        "",
    "plan":         "",
    # False until the startup session check finishes. Without this the
    # UI asks "are you licensed?" before the check completes, gets False,
    # and wrongly shows the login screen every launch.
    "session_checked": False,
}

# Load and validate saved session on startup
def _validate_session():
    try:
        saved = load_license()
        token = saved.get("token", "")
        email = saved.get("email", "")
        if token and email:
            valid, info = verify_token(token, email)
            if valid:
                trial_ended = info.get("trial_ended", False)
                state["licensed"]    = not trial_ended
                state["trial_ended"] = trial_ended
                state["jwt_token"]   = token
                state["email"]       = email
                state["plan"]        = info.get("plan", "")
            else:
                # Token invalid or expired — require login again
                state["licensed"]    = False
                state["trial_ended"] = info.get("trial_ended", False) if isinstance(info, dict) else False
        else:
            # No saved session — user must log in
            state["licensed"] = False
    finally:
        # Always mark the check complete, even if it errored, so the
        # UI never waits forever.
        state["session_checked"] = True

threading.Thread(target=_validate_session, daemon=True).start()


# Load Whisper at startup in background
def _load_whisper():
    state["status"] = "Loading Whisper model..."
    state["transcriber"] = Transcriber(model_size="base")
    state["status"] = "Ready"

threading.Thread(target=_load_whisper, daemon=True).start()


# ── Routes ─────────────────────────────────────────────────────

@app.route("/api/license/status")
def license_status():
    return jsonify({
        "licensed":    state["licensed"],
        "trial_ended": state["trial_ended"],
        "email":       state["email"],
        "plan":        state["plan"],
        "checking":    not state["session_checked"],
    })


@app.route("/api/auth/login", methods=["POST"])
def auth_login():
    data     = request.get_json()
    email    = data.get("email", "").strip()
    password = data.get("password", "").strip()

    if not email or not password:
        return jsonify({"valid": False, "error": "Please enter your email and password"}), 400

    valid, result, info = login(email, password)

    if valid:
        trial_ended = info.get("trial_ended", False) if info else False
        state["licensed"]    = not trial_ended
        state["trial_ended"] = trial_ended
        state["jwt_token"]   = result
        state["email"]       = email
        state["plan"]        = info.get("plan", "") if info else ""
        save_license({"token": result, "email": email})
        return jsonify({"valid": True, "trial_ended": trial_ended})

    # Login refused. If it's an expired account, show the upgrade wall
    # instead of a misleading "wrong password" message.
    if info and info.get("trial_ended"):
        state["licensed"]    = False
        state["trial_ended"] = True
        return jsonify({"valid": False, "trial_ended": True, "error": result}), 403

    return jsonify({"valid": False, "error": result}), 401


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/history")
def get_history():
    return jsonify([e for _, e in load_user_history()])


@app.route("/api/status")
def get_status():
    return jsonify({
        "recording":  state["recording"],
        "paused":     state["paused"],
        "generating": state["generating"],
        "status":     state["status"],
        "transcript": state["transcript"],
        "results":    state["results"],
    })


@app.route("/api/start", methods=["POST"])
def start_recording():
    if state["transcriber"] is None:
        return jsonify({"error": "Whisper is still loading, please wait..."}), 503

    state["recording"]    = True
    state["paused"]       = False
    state["results"]      = None
    # Exact clock time the lecture began — used to group recordings into
    # classes later. Only the date was kept before, which can't tell a
    # Tuesday 2pm class from a Thursday 9am lab.
    state["started_at"]   = datetime.now().isoformat(timespec="seconds")
    state["record_start"] = datetime.now()
    state["status"]       = "Recording..."
    state["transcript"]   = ""
    state["pass1_segs"]   = []   # base model segments in order
    state["pass2_segs"]   = {}   # small model corrections keyed by group
    state["typing_queue"] = []   # words waiting to be typed onto screen

    recorder = Recorder()
    state["recorder"] = recorder

    def loop():
        for item in recorder.record_in_chunks(chunk_seconds=30):
            if not state["recording"]:
                break
            if state["paused"]:
                continue

            pass_num = item[0]
            text     = item[1]

            if pass_num == 1:
                words = item[2]
                state["pass1_segs"].append(text)
                # Queue words for smooth typing effect
                state["typing_queue"].extend(words)

            elif pass_num == 2:
                group = item[2]
                state["pass2_segs"][group] = text
                # Rebuild best transcript
                state["transcript"] = _build_transcript()

    threading.Thread(target=loop, daemon=True).start()
    return jsonify({"ok": True})


def _build_transcript():
    """Returns best available transcript — pass2 where available, pass1 otherwise."""
    pass1 = state.get("pass1_segs", [])
    pass2 = state.get("pass2_segs", {})

    if not pass1:
        return ""

    parts = []
    for i in range(0, len(pass1), 2):
        group = i // 2
        if group in pass2:
            parts.append(pass2[group])
        else:
            parts.extend(pass1[i:i+2])

    return " ".join(parts)


@app.route("/api/words")
def stream_words():
    """
    Server-Sent Events endpoint that streams words one by one
    from the typing queue so the frontend can animate them smoothly.
    """
    def generate():
        import time
        while state.get("recording") or state.get("typing_queue"):
            if state.get("typing_queue"):
                word = state["typing_queue"].pop(0)
                yield f"data: {word}\n\n"
                time.sleep(0.08)   # 80ms between words — smooth typing speed
            else:
                time.sleep(0.05)

    return Response(generate(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache",
                             "X-Accel-Buffering": "no"})


@app.route("/api/pause", methods=["POST"])
def pause_recording():
    state["paused"] = not state["paused"]
    state["status"] = "Paused" if state["paused"] else "Recording..."
    return jsonify({"paused": state["paused"]})


@app.route("/api/history/<int:index>")
def get_history_entry(index):
    scoped = load_user_history()
    if index < 0 or index >= len(scoped):
        return jsonify({"error": "Entry not found"}), 404

    entry  = scoped[index][1]
    folder = entry.get("folder", "")

    def read_file(name):
        path = os.path.join(folder, name)
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
            # Strip the header line we added in output_saver
            lines = content.split("\n")
            if len(lines) > 2:
                return "\n".join(lines[2:]).strip()
        return "File not found."

    return jsonify({
        "name":       entry.get("name", "Lecture"),
        "date":       entry.get("date", ""),
        "duration":   entry.get("duration", ""),
        "status":     entry.get("status", "generated"),
        "notes":      read_file("notes.txt"),
        "flashcards": read_file("flashcards.txt"),
        "summary":    read_file("summary.txt"),
        "transcript": read_file("transcript.txt"),
    })


@app.route("/api/generate-saved/<int:index>", methods=["POST"])
def generate_saved(index):
    """
    Generate notes for a lecture that was saved but never generated
    (recorded while offline or while the site was down).
    """
    scoped = load_user_history()
    if index < 0 or index >= len(scoped):
        return jsonify({"error": "Entry not found"}), 404

    full_index, entry = scoped[index]
    history = load_history()
    folder  = entry.get("folder", "")

    # Read the saved raw transcript
    tpath = os.path.join(folder, "transcript.txt")
    if not os.path.exists(tpath):
        return jsonify({"error": "No transcript found for this lecture"}), 404
    with open(tpath, "r", encoding="utf-8") as f:
        content = f.read()
    lines      = content.split("\n")
    transcript = "\n".join(lines[2:]).strip() if len(lines) > 2 else content.strip()

    if not transcript:
        return jsonify({"error": "This lecture has no transcript to generate from"}), 400

    try:
        results = NoteGenerator(jwt_token=state["jwt_token"]).generate(transcript)
    except Exception as e:
        reason = getattr(e, "reason", "")
        # A raw connection failure means there's no internet — treat as offline
        msg = str(e).lower()
        if not reason and ("connection" in msg or "resolve" in msg or "getaddrinfo" in msg
                           or "max retries" in msg or "timed out" in msg):
            reason = "offline"
        return jsonify({"error": str(e), "reason": reason}), 502

    # Overwrite the saved files with the freshly generated content
    OutputSaver().save({**results, "transcript": transcript}, transcript, folder=folder)

    # Update the history entry: new title, mark as generated
    name = results.get("title", "").strip() or entry.get("name", "Lecture")
    entry["name"]   = name
    entry["status"] = "generated"
    history[full_index] = entry
    save_history(history)

    results["transcript"] = transcript
    return jsonify({**results, "name": name, "status": "generated"})



@app.route("/api/textbook", methods=["POST"])
def add_textbook():
    data          = request.get_json()
    index         = data.get("index", -1)
    textbook_text = data.get("text", "").strip()

    if not textbook_text:
        return jsonify({"error": "No textbook text provided"}), 400

    scoped = load_user_history()
    if index == -1:
        if not scoped:
            return jsonify({"error": "Entry not found"}), 404
        entry = scoped[-1][1]
    elif 0 <= index < len(scoped):
        entry = scoped[index][1]
    else:
        return jsonify({"error": "Entry not found"}), 404

    folder = entry.get("folder", "")

    def read_file(name):
        path = os.path.join(folder, name)
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
            lines = content.split("\n")
            return "\n".join(lines[2:]).strip() if len(lines) > 2 else content.strip()
        return ""

    transcript = read_file("transcript.txt")
    summary    = read_file("summary.txt")   # keep this unchanged

    if not transcript:
        return jsonify({"error": "Transcript not found"}), 404

    def generate():
        try:
            state["generating"] = True
            state["status"]     = "Combining lecture and textbook content..."

            generator = NoteGenerator()
            results   = generator.generate_with_textbook(transcript, textbook_text)

            new_notes      = results.get("notes", "")
            new_flashcards = results.get("flashcards", "")

            # Save updated notes and flashcards to the SAME folder
            if new_notes:
                with open(os.path.join(folder, "notes.txt"), "w", encoding="utf-8") as f:
                    f.write("LECTURE NOTES\n========================================\n\n" + new_notes)

            if new_flashcards:
                with open(os.path.join(folder, "flashcards.txt"), "w", encoding="utf-8") as f:
                    f.write("FLASHCARDS\n========================================\n\n" + new_flashcards)

            # Return updated results — summary stays the same
            state["results"] = {
                "notes":      new_notes,
                "flashcards": new_flashcards,
                "summary":    summary,
                "transcript": transcript,
                "entry":      entry,
                "_index":     index if index != -1 else len(scoped) - 1,
            }
            state["generating"] = False
            state["status"]     = "Done!"

        except Exception as e:
            state["status"]     = f"Error: {e}"
            state["generating"] = False

    state["results"] = None
    threading.Thread(target=generate, daemon=True).start()
    return jsonify({"ok": True})


@app.route("/api/rename", methods=["POST"])
def rename_entry():
    data    = request.get_json()
    index   = data.get("index", -1)
    name    = data.get("name", "").strip()
    history = load_history()
    scoped  = load_user_history()

    if index == -1:
        # Most recent entry belonging to this account (just recorded)
        if scoped:
            history[scoped[-1][0]]["name"] = name
    elif 0 <= index < len(scoped):
        history[scoped[index][0]]["name"] = name

    save_history(history)
    return jsonify({"ok": True})


@app.route("/api/auth/logout", methods=["POST"])
def auth_logout():
    """Sign the user out and clear the saved session from disk."""
    state["licensed"]    = False
    state["trial_ended"] = False
    state["jwt_token"]   = ""
    state["email"]       = ""
    state["plan"]        = ""
    state["session_checked"] = True
    try:
        if os.path.exists(LICENSE_FILE):
            os.remove(LICENSE_FILE)
    except Exception:
        pass
    return jsonify({"ok": True})


@app.route("/api/lecture/<int:index>/flashcards", methods=["POST"])
def save_flashcards(index):
    """
    Persist edited flashcards back to the lecture's folder. Without this
    every edit was lost as soon as the lecture was closed.
    """
    scoped = load_user_history()
    if index < 0 or index >= len(scoped):
        return jsonify({"error": "Entry not found"}), 404

    entry  = scoped[index][1]
    folder = entry.get("folder", "")
    text   = (request.get_json() or {}).get("flashcards", "")

    path = os.path.join(folder, "flashcards.txt")
    if not os.path.exists(path):
        return jsonify({"error": "Lecture files not found"}), 404

    try:
        # Keep the header line output_saver wrote, replace the body.
        with open(path, "r", encoding="utf-8") as f:
            existing = f.read().split("\n")
        header = "\n".join(existing[:2]) if len(existing) > 2 else ""
        with open(path, "w", encoding="utf-8") as f:
            f.write((header + "\n" + text) if header else text)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    return jsonify({"ok": True})


@app.route("/api/lecture/<int:index>/progress", methods=["GET", "POST"])
def card_progress(index):
    """Read or update per-card mastery for a lecture."""
    scoped = load_user_history()
    if index < 0 or index >= len(scoped):
        return jsonify({"error": "Entry not found"}), 404

    folder = scoped[index][1].get("folder", "")

    if request.method == "GET":
        return jsonify(store.load_progress(folder))

    data = request.get_json() or {}
    card = store.record_answer(
        folder,
        data.get("card", ""),
        bool(data.get("correct")),
        bool(data.get("confident")),
    )
    return jsonify(card)


@app.route("/api/classes", methods=["GET", "POST"])
def classes_route():
    email = current_email()
    if not email:
        return jsonify([]) if request.method == "GET" else (jsonify({"error": "Not signed in"}), 401)

    if request.method == "GET":
        return jsonify(store.load_classes(email))

    data = request.get_json() or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "Class needs a name"}), 400

    return jsonify(store.create_class(email, name, data.get("days"), data.get("times")))


@app.route("/api/classes/<class_id>", methods=["PATCH", "DELETE"])
def class_detail(class_id):
    email = current_email()
    if not email:
        return jsonify({"error": "Not signed in"}), 401

    if request.method == "DELETE":
        if not store.delete_class(email, class_id):
            return jsonify({"error": "Class not found"}), 404
        # Lectures survive — they just become unassigned.
        history = load_history()
        for e in history:
            if e.get("class_id") == class_id:
                e["class_id"] = None
        save_history(history)
        return jsonify({"ok": True})

    data    = request.get_json() or {}
    updated = store.update_class(email, class_id, **data)
    if not updated:
        return jsonify({"error": "Class not found"}), 404
    return jsonify(updated)


@app.route("/api/classes/merge", methods=["POST"])
def merge_classes_route():
    """Fold one class into another and repoint its lectures."""
    email = current_email()
    if not email:
        return jsonify({"error": "Not signed in"}), 401

    data   = request.get_json() or {}
    keep   = data.get("keep_id")
    absorb = data.get("absorb_id")

    if not store.merge_classes(email, keep, absorb):
        return jsonify({"error": "Could not merge those classes"}), 400

    history = load_history()
    for e in history:
        if e.get("class_id") == absorb:
            e["class_id"] = keep
    save_history(history)
    return jsonify({"ok": True})


@app.route("/api/lecture/<int:index>/class", methods=["POST"])
def assign_class(index):
    """Assign (or clear) the class a lecture belongs to."""
    scoped = load_user_history()
    if index < 0 or index >= len(scoped):
        return jsonify({"error": "Entry not found"}), 404

    full_index = scoped[index][0]
    history    = load_history()
    history[full_index]["class_id"] = (request.get_json() or {}).get("class_id")
    save_history(history)
    return jsonify({"ok": True})


def _read_flashcards(folder):
    """Pull the flashcard text out of a lecture folder, header stripped."""
    path = os.path.join(folder, "flashcards.txt")
    if not os.path.exists(path):
        return ""
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        lines = content.split("\n")
        return "\n".join(lines[2:]).strip() if len(lines) > 2 else content.strip()
    except Exception:
        return ""


@app.route("/api/cram/build", methods=["POST"])
def build_cram():
    """
    Build (or top up) the question pool for a set of lectures.

    Cached per class so a second cram session doesn't pay to regenerate.
    When new lectures have been recorded since, only those are generated
    and merged into the existing pool.
    """
    data      = request.get_json() or {}
    indices   = data.get("lectures", [])
    class_id  = data.get("class_id") or "_adhoc"
    minutes   = int(data.get("minutes", 15))
    # A small opening batch returns in a few seconds so the student can
    # start while the full set generates behind them.
    quick     = bool(data.get("quick"))

    scoped = load_user_history()
    chosen = [scoped[i] for i in indices if 0 <= i < len(scoped)]
    if not chosen:
        return jsonify({"error": "No lectures selected"}), 400

    # Roughly two questions per minute, capped so one session can't
    # generate an unusable wall of questions.
    want = max(10, min(minutes * 2, 60))

    # Opening batch: pull questions already saved on disk from previous
    # practice tests. No API call, no wait — the session starts instantly
    # and the generated set catches up behind it.
    if quick:
        opening = []
        for _, entry in chosen:
            folder = entry.get("folder", "")
            path   = os.path.join(folder, "practice_test.json")
            if not os.path.exists(path):
                continue
            try:
                with open(path, "r", encoding="utf-8") as f:
                    saved = json.load(f)
                for q in saved.get("questions", []):
                    # Open-ended needs Claude to grade — not usable here
                    if q.get("type") in ("mc", "tf"):
                        q["lecture"] = entry.get("name", "Lecture")
                        opening.append(q)
            except Exception:
                continue

        # No saved tests for these lectures — fall back to flashcards,
        # which every lecture always has. Recall-style warm-up questions
        # instead of an empty wait.
        if not opening:
            for _, entry in chosen:
                cards = _read_flashcards(entry.get("folder", ""))
                if not cards:
                    continue
                q_text = None
                for line in cards.split("\n"):
                    line = line.strip()
                    if line.startswith("Q:"):
                        q_text = line[2:].strip()
                    elif line.startswith("A:") and q_text:
                        opening.append({
                            "type":     "recall",
                            "question": q_text,
                            "answer":   line[2:].strip(),
                            "lecture":  entry.get("name", "Lecture"),
                        })
                        q_text = None

        random.shuffle(opening)
        return jsonify({"questions": opening[:12], "quick": True, "cached": True})

    cached       = store.load_cram(class_id)
    have_folders = set(cached.get("lectures", [])) if cached else set()

    # Newest first — recent material is least consolidated
    chosen = sorted(chosen, key=lambda t: t[1].get("started_at", ""), reverse=True)

    new_lectures = []
    for _, entry in chosen:
        folder = entry.get("folder", "")
        if folder in have_folders:
            continue
        cards = _read_flashcards(folder)
        if cards:
            new_lectures.append({
                "folder":     folder,
                "title":      entry.get("name", "Lecture"),
                "flashcards": cards,
            })

    # A ceiling only, not a target — the prompt tells Claude to stop when
    # it runs out of distinct facts, so this just prevents an absurd ask
    # when a student picks 40 lectures for a 15-minute session.
    available = sum(l["flashcards"].count("Q:") for l in new_lectures)
    if available:
        want = min(want, available * 3)



    # Everything already generated — serve the cache
    if not new_lectures and cached:
        return jsonify({"questions": cached.get("questions", []), "cached": True})

    if not new_lectures:
        return jsonify({"error": "These lectures have no flashcards to build from"}), 400

    # Cap per the 40-lecture limit
    new_lectures = new_lectures[:40]

    try:
        result = NoteGenerator(jwt_token=state["jwt_token"]).generate_cram(
            [{"title": l["title"], "flashcards": l["flashcards"]} for l in new_lectures],
            count=want,
        )
    except Exception as e:
        reason = getattr(e, "reason", "")
        msg = str(e).lower()
        if not reason and ("connection" in msg or "resolve" in msg or "timed out" in msg):
            reason = "offline"
        return jsonify({"error": str(e), "reason": reason}), 502

    questions = result.get("questions", [])
    folders   = [l["folder"] for l in new_lectures]

    if quick:
        return jsonify({"questions": questions, "cached": False, "quick": True})

    if cached:
        store.merge_cram(class_id, questions, folders)
        pool = store.load_cram(class_id).get("questions", [])
    else:
        store.save_cram(class_id, questions, folders)
        pool = questions

    return jsonify({"questions": pool, "cached": False})


@app.route("/api/feedback", methods=["POST"])
def send_feedback():
    """
    Forward a feature suggestion to the support inbox via the website's
    existing contact endpoint — no new mail plumbing needed.
    """
    message = (request.get_json() or {}).get("message", "").strip()
    if not message:
        return jsonify({"error": "Message is empty"}), 400
    if len(message) > 4000:
        return jsonify({"error": "That message is too long"}), 400

    # Crude per-process rate limit. An open message endpoint in a desktop
    # app will get spammed eventually.
    now  = datetime.now().timestamp()
    last = state.get("last_feedback_at", 0)
    if now - last < 30:
        return jsonify({"error": "Give it a moment before sending another"}), 429

    email   = current_email() or "unknown"
    version = "1.2.8"

    try:
        resp = requests.post(
            f"{WEBSITE_URL}/api/contact",
            json={
                "name":    "In-app suggestion",
                "email":   email,
                "subject": "Feature request (in-app)",
                # Version included automatically — "this is broken" is far
                # more useful with a build number attached.
                "message": f"{message}\n\n---\nApp version: {version}",
            },
            timeout=20,
        )
        if resp.status_code >= 400:
            return jsonify({"error": "Could not send right now"}), 502
    except requests.exceptions.RequestException:
        return jsonify({"error": "No internet connection"}), 503
    except Exception:
        return jsonify({"error": "Could not send right now"}), 502

    state["last_feedback_at"] = now
    return jsonify({"ok": True})


@app.route("/api/practice-test", methods=["POST"])
def practice_test():
    """
    Generate a practice test, or return the saved one.

    Tests are written to the lecture folder so reopening a lecture
    doesn't pay to regenerate the same questions — and so Cram can
    reuse them instantly.
    """
    data       = request.get_json() or {}
    transcript = data.get("transcript", "").strip()
    index      = data.get("index")

    folder = ""
    if index is not None:
        scoped = load_user_history()
        if 0 <= index < len(scoped):
            folder = scoped[index][1].get("folder", "")

    # Serve the saved test if we already have one
    if folder:
        saved = os.path.join(folder, "practice_test.json")
        if os.path.exists(saved) and not data.get("force"):
            try:
                with open(saved, "r", encoding="utf-8") as f:
                    return jsonify(json.load(f))
            except Exception:
                pass

    if not transcript:
        return jsonify({"error": "No transcript provided"}), 400

    try:
        result = NoteGenerator(jwt_token=state["jwt_token"]).generate_practice_test(transcript)
    except Exception as e:
        reason = getattr(e, "reason", "")
        return jsonify({"error": str(e), "reason": reason}), 502

    # Persist for next time
    if folder and result.get("questions"):
        try:
            with open(os.path.join(folder, "practice_test.json"), "w", encoding="utf-8") as f:
                json.dump(result, f, indent=2)
        except Exception:
            pass

    return jsonify(result)


@app.route("/api/rate-answer", methods=["POST"])
def rate_answer():
    data = request.get_json()
    try:
        import requests as req
        SERVER_URL = "https://web-production-2b0e5.up.railway.app"
        APP_SECRET = "octis2026secretkey"
        response   = req.post(
            f"{SERVER_URL}/rate-answer",
            headers={"Content-Type": "application/json", "X-Octis-Secret": APP_SECRET,
                     "X-Auth-Token": state.get("jwt_token", "")},
            json=data,
            timeout=30,
        )
        return jsonify(response.json())
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/stop", methods=["POST"])
def stop_recording():
    state["recording"]  = False
    state["paused"]     = False
    state["generating"] = True
    state["status"]     = "Generating your study materials..."

    if state["recorder"]:
        state["recorder"].stop_flag.set()

    duration_mins = int(
        (datetime.now() - state["record_start"]).total_seconds() / 60
    ) if state["record_start"] else 0

    def generate():
        try:
            transcript = _build_transcript().strip()
            if not transcript:
                state["status"]     = "No speech detected. Try again."
                state["generating"] = False
                return

            try:
                results       = NoteGenerator(jwt_token=state["jwt_token"]).generate(transcript)
            except Exception as gen_err:
                # Generation failed (no internet, website down, or access blocked).
                # Never lose the lecture — save the raw transcript as "ungenerated"
                # so the user can generate notes later from the history list.
                _save_ungenerated(transcript, duration_mins, str(gen_err))
                return

            output_folder = OutputSaver().save(results, transcript)

            # Save transcript to results so UI can show it
            results["transcript"] = transcript

            # Use Claude's generated title
            name = results.get("title", "").strip()
            if not name:
                name = f"Lecture {datetime.now().strftime('%b %d')}"

            entry = {
                "name":     name,
                "date":     datetime.now().strftime("%b %d, %Y"),
                "duration": f"{duration_mins} min",
                "folder":   output_folder,
                "status":     "generated",
                "email":      (state.get("email") or "").strip().lower(),
                "started_at": state.get("started_at", ""),
                "class_id":   None,
            }
            history = load_history()
            history.append(entry)
            save_history(history)

            state["results"]    = {**results, "entry": entry}
            state["generating"] = False
            state["status"]     = "Done!"

        except Exception as e:
            state["status"]     = f"Error: {e}"
            state["generating"] = False

    threading.Thread(target=generate, daemon=True).start()
    return jsonify({"ok": True})


def _save_ungenerated(transcript, duration_mins, reason=""):
    """
    Save a lecture that couldn't be generated (offline, website down,
    or access blocked). The raw transcript is preserved so the user
    can generate notes later. Shows up in history marked 'ungenerated'.
    """
    try:
        results = {
            "title":      "",
            "notes":      "",
            "flashcards": "",
            "summary":    "",
            "transcript": transcript,
        }
        output_folder = OutputSaver().save(results, transcript)

        name = f"Lecture {datetime.now().strftime('%b %d')}"
        entry = {
            "name":     name,
            "date":     datetime.now().strftime("%b %d, %Y"),
            "duration": f"{duration_mins} min",
            "folder":   output_folder,
            "status":     "ungenerated",
            "email":      (state.get("email") or "").strip().lower(),
            "started_at": state.get("started_at", ""),
            "class_id":   None,
        }
        history = load_history()
        history.append(entry)
        save_history(history)

        state["results"]    = None
        state["generating"] = False
        state["status"]     = "Saved. Couldn't generate notes right now — your lecture is safe in your recordings and you can generate it later."
    except Exception as e:
        state["status"]     = f"Error saving lecture: {e}"
        state["generating"] = False


# ── Launch ─────────────────────────────────────────────────────
if __name__ == "__main__":
    app.run(debug=False, port=5000, use_reloader=False)
