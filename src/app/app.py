from __future__ import annotations
import os
import json
import re
from datetime import date, timedelta
from typing import List, Dict, Any

import requests
from dateutil import parser as dateparser
from flask import Flask, render_template, request, redirect, url_for, flash

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret")

# In-memory storage for the POC (resets on restart)
SCHEDULE: List[Dict[str, Any]] = []

# Helper: normalize and validate a schedule item
# Schema: {day: "Mon".."Sun", start: "09:00", end: "10:30", title: str, note?: str, provider?: str}
DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def current_week_start(today: date | None = None) -> date:
    base = today or date.today()
    return base - timedelta(days=base.weekday())


def week_bounds() -> tuple[date, date]:
    start = current_week_start()
    return start, start + timedelta(days=6)


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


def add_item(
    day: str,
    start: str,
    end: str,
    title: str,
    *,
    note: str | None = None,
    provider: str | None = None,
) -> None:
    day_norm = day.strip().title()[:3]
    if day_norm not in DAYS:
        raise ValueError("Day must be one of Mon..Sun")
    start_hhmm = _to_hhmm(start)
    end_hhmm = _to_hhmm(end)
    if end_hhmm <= start_hhmm:
        raise ValueError("End must be after start")
    provider_name = (provider or "Unassigned").strip() or "Unassigned"
    SCHEDULE.append(
        {
            "day": day_norm,
            "start": start_hhmm,
            "end": end_hhmm,
            "title": title.strip(),
            "note": (note or "").strip(),
            "provider": provider_name,
        }
    )


def clear_schedule() -> None:
    SCHEDULE.clear()


def sorted_schedule() -> List[Dict[str, Any]]:
    day_index = {d: i for i, d in enumerate(DAYS)}
    normalised_items: List[Dict[str, Any]] = []
    for item in SCHEDULE:
        normalised_items.append(
            {
                **item,
                "provider": item.get("provider", "Unassigned") or "Unassigned",
            }
        )
    return sorted(normalised_items, key=lambda x: (day_index[x["day"]], x["start"]))


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
    schedule_items = sorted_schedule()
    week_start, week_end = week_bounds()
    day_dates = {
        day: week_start + timedelta(days=idx)
        for idx, day in enumerate(DAYS)
    }
    return render_template(
        "index.html",
        schedule=schedule_items,
        week_start=week_start,
        week_end=week_end,
        day_dates=day_dates,
    )


@app.route("/add", methods=["POST"])
def add():
    try:
        submitted_date = request.form.get("date", "")
        day_value = request.form.get("day", "Mon")
        if submitted_date:
            try:
                parsed_date = date.fromisoformat(submitted_date)
                day_value = parsed_date.strftime("%a")
            except ValueError:
                pass
        add_item(
            day_value,
            request.form.get("start", "09:00"),
            request.form.get("end", "10:00"),
            request.form.get("title", "Untitled"),
            note=request.form.get("note", ""),
            provider=request.form.get("provider", ""),
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
                note=it.get("note", ""),
                provider=it.get("provider", ""),
            )
        flash(f"Generated {len(items)} items from LLM", "success")
    except Exception as e:
        flash(f"Failed to generate using Ollama: {e}", "danger")
    return redirect(url_for("index"))


if __name__ == "__main__":
    # Enable `python app.py` local runs; otherwise use `flask --app app run --debug`
    app.run(debug=True)
