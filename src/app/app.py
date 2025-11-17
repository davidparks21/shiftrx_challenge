from __future__ import annotations
import os
import json
import re
import requests
import markdown
from datetime import date, timedelta, datetime
from typing import List, Dict, Any
from dateutil import parser as dateparser
from flask import Flask, render_template, request, redirect, url_for, flash, session

import data_access_layer.data_store as db
from data_object_model.application_state import Schedule, Entry, DateRange
from data_object_model.agent_communication import AgentQuery, AgentResponse
from model_access_layer.agent import handle_user_prompt


app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret")

# In-memory storage for the POC (resets on restart)
SCHEDULE: List[Dict[str, Any]] = []

# Helper: normalize and validate a schedule item
# Schema: {day: "Mon".."Sun", start: "09:00", end: "10:30", title: str, note?: str, provider?: str}
DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

# Default configuration parameters (future update should centralize these)
DEFAULT_DATE_RANGE_DAYS = 7


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
        provider: str | None = None) -> None:
    """
    Normalize and validate an item, then persist it as an Entry via the data store.

    The function keeps the same public API as before (day/start/end/title/note/provider)
    but now creates an Entry object and stores it in the DB.
    """
    # Normalise day ("Mon".."Sun")
    day_norm = day.strip().title()[:3]
    if day_norm not in DAYS:
        raise ValueError("Day must be one of Mon..Sun")

    # Normalise and validate times using the existing helper
    start_hhmm = _to_hhmm(start)
    end_hhmm = _to_hhmm(end)
    if end_hhmm <= start_hhmm:
        raise ValueError("End must be after start")

    # Convert HH:MM strings to time objects for Entry
    start_time = datetime.strptime(start_hhmm, "%H:%M").time()
    end_time = datetime.strptime(end_hhmm, "%H:%M").time()

    # Map day-of-week to a concrete date in the current week
    week_start = current_week_start()
    day_index = {d: i for i, d in enumerate(DAYS)}
    entry_date = week_start + timedelta(days=day_index[day_norm])

    # Build Entry object
    entry = Entry(
        entry_id=-1,
        entry_date=entry_date,
        start_time=start_time,
        end_time=end_time,
        title=title,
        provider=provider,
        note=note
    )

    # Persist via data store; no users yet, so user_id=None
    db.add_entry(entry, user_id=None)


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
    daterange = session.get("daterange", None)
    if daterange is None:
        datetime_to = datetime.now()
        datetime_from = datetime_to - timedelta(days=DEFAULT_DATE_RANGE_DAYS)
        daterange = DateRange(datetime_from, datetime_to)
    else:
        daterange = DateRange.from_primitive(daterange)

    schedule = db.get_schedule(1, daterange)
    session["daterange"] = daterange.to_primitive()

    # Convert LLM response markdown → HTML if present
    conversation = session.get("conversation")
    if conversation and conversation.get("response"):
        html = markdown.markdown(conversation["response"])
        session["conversation"]["html_response"] = html

    return render_template("index.html", schedule=schedule)


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


@app.route("/clear", methods=["POST", "GET"])
def clear():
    clear_schedule()
    flash("Schedule items cleared", "warning")
    return redirect(url_for("index"))


@app.post("/clear_conversation")
def clear_conversation():
    session.pop("conversation", None)
    return redirect(url_for("index"))


@app.route("/generate", methods=["POST"])
def generate():
    # Processes the query and place the response in session["conversation"]
    user_prompt = request.form.get("user_prompt")
    agent_query = AgentQuery(user_prompt=user_prompt)
    daterange = DateRange.from_primitive(session.get("daterange"))
    schedule = db.get_schedule(1, daterange)
    session["conversation"] = handle_user_prompt(agent_query, schedule)
    # Update the session DateRange in case a tool made an update.
    session["daterange"] = schedule.daterange.to_primitive()
    return redirect(url_for("index"))


@app.route("/remove", methods=["POST"])
def remove():
    # Get list of selected entry IDs from the form
    raw_ids = request.form.getlist("selected_items")

    if not raw_ids:
        flash("No items selected to remove.", "warning")
        return redirect(url_for("index"))

    # Validate & convert to integers
    try:
        entry_ids = [int(x) for x in raw_ids]
    except ValueError:
        flash("Invalid selection received.", "danger")
        return redirect(url_for("index"))

    # Fetch the corresponding Entry objects
    entries = db.get_entries_by_ids(entry_ids)

    if not entries:
        flash("No matching schedule items found.", "warning")
        return redirect(url_for("index"))

    # Remove each entry; using user_id=1 to match get_schedule()
    deleted_count = 0
    for entry in entries:
        deleted_count += db.remove_entry(entry, user_id=1)

    if deleted_count == 0:
        flash("No schedule items were removed.", "warning")
    else:
        flash(f"Removed {deleted_count} item{'s' if deleted_count != 1 else ''} from the schedule.", "success")

    return redirect(url_for("index"))

if __name__ == "__main__":
    # Enable `python app.py` local runs; otherwise use `flask --app app run --debug`
    app.run(debug=True)
