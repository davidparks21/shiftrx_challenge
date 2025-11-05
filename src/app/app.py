from __future__ import annotations
import os
import json
import re
from typing import List, Dict, Any

import requests
from dateutil import parser as dateparser
from flask import Flask, render_template, request, redirect, url_for, flash

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret")

# In-memory storage for the POC (resets on restart)
SCHEDULE: List[Dict[str, Any]] = []

# Helper: normalize and validate a schedule item
# Schema: {day: "Mon".."Sun", start: "09:00", end: "10:30", title: str, note?: str}
DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def _to_hhmm(s: str) -> str:
    """Parse various time inputs to 'HH:MM' (24h)."""
    try:
        t = dateparser.parse(s).time()
        return f"{t.hour:02d}:{t.minute:02d}"
    except Exception:
        # fallback: accept already-well-formed HH:MM
        if re.match(r"^\d{2}:\d{2}$", s):
            return s
        raise ValueError(f"Invalid time: {s}")


def add_item(day: str, start: str, end: str, title: str, note: str | None = None) -> None:
    day_norm = day.strip().title()[:3]
    if day_norm not in DAYS:
        raise ValueError("Day must be one of Mon..Sun")
    start_hhmm = _to_hhmm(start)
    end_hhmm = _to_hhmm(end)
    if end_hhmm <= start_hhmm:
        raise ValueError("End must be after start")
    SCHEDULE.append(
        {
            "day": day_norm,
            "start": start_hhmm,
            "end": end_hhmm,
            "title": title.strip(),
            "note": (note or "").strip(),
        }
    )


def clear_schedule() -> None:
    SCHEDULE.clear()


def sorted_schedule() -> List[Dict[str, Any]]:
    day_index = {d: i for i, d in enumerate(DAYS)}
    return sorted(SCHEDULE, key=lambda x: (day_index[x["day"]], x["start"]))


# ----------------------------
# Ollama integration (local)
# ----------------------------
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "llama3.1")

# Also store in Flask config so templates can use {{ config['OLLAMA_MODEL'] }}
app.config["OLLAMA_MODEL"] = OLLAMA_MODEL

SYSTEM_PROMPT = (
    "You are a helpful assistant that plans a weekly schedule. "
    "Return ONLY valid JSON matching this schema: {\n"
    '  "items": [\n'
    '    { "day": one of Mon/Tue/Wed/Thu/Fri/Sat/Sun,\n'
    '      "start": "HH:MM", "end": "HH:MM",\n'
    '      "title": string, "note": optional string }\n'
    "  ]\n"
    "}. No extra commentary. Times in 24-hour local time."
)


def call_ollama_chat(user_prompt: str) -> Dict[str, Any]:
    """Call Ollama's /api/chat endpoint and return parsed JSON schedule.
    Falls back to extracting the first JSON object found in the response.
    """
    url = f"{OLLAMA_URL}/api/chat"
    payload = {
        "model": OLLAMA_MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        "stream": False,
    }
    try:
        resp = requests.post(url, json=payload, timeout=120)
        resp.raise_for_status()
        data = resp.json()
        content = data.get("message", {}).get("content", "")

        # Try direct JSON first
        try:
            return json.loads(content)
        except Exception:
            pass

        # Fallback: extract first JSON object from text
        m = re.search(r"\{[\s\S]*\}", content)
        if not m:
            raise ValueError("LLM did not return JSON")
        return json.loads(m.group(0))
    except Exception as e:
        raise RuntimeError(f"Ollama error: {e}") from e


# ----------------------------
# Jinja context helpers
# ----------------------------
@app.context_processor
def inject_env():
    # Keeps your existing {{ env('KEY', default) }} helper
    # …and also injects {{ environ.get('KEY') }} so your current template works unchanged.
    return {
        "env": lambda k, default=None: os.environ.get(k, default),
        "environ": os.environ,
        "DAYS": DAYS,
        "config": app.config,
    }


# ----------------------------
# Routes
# ----------------------------
@app.route("/", methods=["GET"])
def index():
    return render_template("index.html", schedule=sorted_schedule(), days=DAYS)


@app.route("/add", methods=["POST"])
def add():
    try:
        add_item(
            request.form.get("day", "Mon"),
            request.form.get("start", "09:00"),
            request.form.get("end", "10:00"),
            request.form.get("title", "Untitled"),
            request.form.get("note", ""),
        )
        flash("Added item", "success")
    except Exception as e:
        flash(str(e), "danger")
    return redirect(url_for("index"))


@app.route("/clear", methods=["POST"])
def clear():
    clear_schedule()
    flash("Schedule cleared", "warning")
    return redirect(url_for("index"))


@app.route("/generate", methods=["POST"])
def generate():
    goals = request.form.get("goals", "")
    seed = request.form.get("seed", "Mon-Fri 09:00-17:00 work blocks; daily exercise; 2h learning")
    prompt = (
        "Create a realistic weekly plan based on these goals. "
        "Use 30–120 minute blocks, avoid overlaps. "
        f"Goals: {goals or 'Focus work, exercise, learning, and errands.'} "
        f"Seed: {seed}."
    )
    try:
        result = call_ollama_chat(prompt)
        items = result.get("items", [])
        # Basic validation and load
        clear_schedule()
        for it in items:
            add_item(
                it.get("day", "Mon"),
                it.get("start", "09:00"),
                it.get("end", "10:00"),
                it.get("title", "Task"),
                it.get("note", ""),
            )
        flash(f"Generated {len(items)} items from LLM", "success")
    except Exception as e:
        flash(f"Failed to generate using Ollama: {e}", "danger")
    return redirect(url_for("index"))


if __name__ == "__main__":
    # Enable `python app.py` local runs; otherwise use `flask --app app run --debug`
    app.run(debug=True)
