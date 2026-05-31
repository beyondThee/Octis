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
import webbrowser
import json
import os
from datetime import datetime
from flask import Flask, render_template, jsonify, request, Response
from recorder import Recorder
from transcriber import Transcriber
from note_generator import NoteGenerator
from output_saver import OutputSaver

app = Flask(__name__, static_folder='static', static_url_path='/static')

# ── Global state ───────────────────────────────────────────────
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
}

OCTIS_DATA_DIR = os.path.join(os.path.expanduser("~"), "Documents", "Octis")
os.makedirs(OCTIS_DATA_DIR, exist_ok=True)
HISTORY_FILE = os.path.join(OCTIS_DATA_DIR, "lecture_history.json")


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


# Load Whisper at startup in background
def _load_whisper():
    state["status"] = "Loading Whisper model..."
    state["transcriber"] = Transcriber(model_size="base")
    state["status"] = "Ready"

threading.Thread(target=_load_whisper, daemon=True).start()


# ── Routes ─────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/history")
def get_history():
    return jsonify(load_history())


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
    history = load_history()
    if index < 0 or index >= len(history):
        return jsonify({"error": "Entry not found"}), 404

    entry  = history[index]
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
        "notes":      read_file("notes.txt"),
        "flashcards": read_file("flashcards.txt"),
        "summary":    read_file("summary.txt"),
        "transcript": read_file("transcript.txt"),
    })



@app.route("/api/textbook", methods=["POST"])
def add_textbook():
    data          = request.get_json()
    index         = data.get("index", -1)
    textbook_text = data.get("text", "").strip()

    if not textbook_text:
        return jsonify({"error": "No textbook text provided"}), 400

    history = load_history()
    if index == -1:
        actual_index = len(history) - 1
    elif 0 <= index < len(history):
        actual_index = index
    else:
        return jsonify({"error": "Entry not found"}), 404

    entry  = history[actual_index]
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
                "_index":     actual_index,
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

    if index == -1:
        # Most recent entry (just recorded)
        if history:
            history[-1]["name"] = name
    elif 0 <= index < len(history):
        history[index]["name"] = name

    save_history(history)
    return jsonify({"ok": True})


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

            results       = NoteGenerator().generate(transcript)
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


# ── Launch ─────────────────────────────────────────────────────
if __name__ == "__main__":
    app.run(debug=False, port=5000, use_reloader=False)