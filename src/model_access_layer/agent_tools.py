"""
Agent-callable tools are called by an LLM and return text to the LLM and
allow the LLM to interact with the application.
"""
from data_object_model.application_state import Schedule, DateRange, Entry
from data_access_layer import data_store
from datetime import datetime, timedelta, date
from typing import Any, Dict, List, Optional, Sequence, Union


def filter_date_range(schedule: Schedule, from_date: str, to_date: str) -> Tuple[Schedule, str]:
    """Filter appointment entries by an inclusive date range.
    Use only when the user asks to restrict results by date.
    If the request lacks a clear start or end date, or uses an ambiguous date format,
    ask the user to clarify before calling.

    Parameters
    ----------
    schedule : Schedule
        A `Schedule` object from the `data_object_model` top-level package.
        Represents the user's current schedule, stored in the user's session within the application.
        This is a mutable object, changes to it will be reflected back to the user.
    from_date : str
        The start date of the filter range (inclusive). Should be a valid, unambiguous date string.
    to_date : str
        The end date of the filter range (inclusive). Should be a valid, unambiguous date string.

    Returns
    -------
    dict
        Returns a dictionary containing keys {result=Success, from_date, to_date}
    """
    schedule.daterange = DateRange(from_date, to_date)
    tool_response = {
        "result": "Success",
        "from_date": f"{from_date}",
        "to_date": f"{to_date}"
    }
    return tool_response


def get_schedule_table(schedule: Schedule) -> Dict[str, Any]:
    """
    Return the current appointment table exactly as shown to the user.

    Read-only. Does NOT mutate the Schedule object.
    Assumes `schedule.entries` already reflects any active filters (e.g., date range).

    Returns
    -------
    dict
        {
            "daterange": { "from_date": str, "to_date": str },
            "rows": [
                {
                    "entry_id": int,
                    "date": "YYYY-MM-DD",
                    "start_time": "HH:MM:SS",
                    "end_time": "HH:MM:SS",
                    "title": str or None,
                    "provider": str or None,
                    "note": str or None,
                    "is_selected": bool
                },
                ...
            ]
        }
    """
    entries = schedule.entries or []

    rows = []
    for entry in entries:
        rows.append(
            {
                "entry_id": entry.entry_id,
                "date": entry.entry_date.isoformat(),
                "start_time": entry.start_time.strftime("%H:%M:%S"),
                "end_time": entry.end_time.strftime("%H:%M:%S"),
                "title": entry.title,
                "provider": entry.provider,
                "note": entry.note,
                "is_selected": entry.is_selected,
            }
        )

    return {
        "daterange": {
            "from_date": schedule.daterange.date_from.strftime("%Y-%m-%d %H:%M:%S"),
            "to_date": schedule.daterange.date_to.strftime("%Y-%m-%d %H:%M:%S"),
        },
        "rows": rows,
    }


def filter_range(schedule: Schedule, entry_ids: List[str]) -> Dict[str, Any]:
    """
    Select a subset of entries by entry ID based on the user's stated criteria.

    This function mutates `schedule.entries`:
      - Entries whose `entry_id` is in `entry_ids` will have `is_selected = True`.
      - All other entries will have `is_selected = False`.

    Parameters
    ----------
    schedule : Schedule
        A `Schedule` object from the `data_object_model` top-level package.
        Represents the user's current schedule, stored in the user's session
        within the application. This is a mutable object; changes will be
        reflected in downstream application logic.
    entry_ids : List[str]
        List of entry IDs to select. These come from the tool call payload and
        are expected to be strings that can be converted to integers.

    Returns
    -------
    dict
        A dictionary summarizing the selection:
          {
              "selected_entry_ids": [str, ...],      # actually matched entries
              "not_found_entry_ids": [str, ...],     # valid IDs that did not match any Entry
              "invalid_entry_ids": [str, ...],       # IDs that could not be parsed as int
              "total_selected": int
          }

    NOTE: THIS WAS REMOVED FOR TIME CONSTRAINT REASONS, THE ORIGINAL FUNCTION_DEFINITION.JSON
    IS LISTED BELOW IN CASE IT'S ADDED AGAIN.
      {
        "type": "function",
        "function": {
          "name": "filter_range",
          "description": "Select a subset of entries by entry ID based on the user's stated criteria (e.g., all entries with Provider = 'Dr. Patel'). Determine the matching entries from context first, then pass their entry IDs. If the criteria are ambiguous or cannot be satisfied, ask the user to clarify before calling.",
          "parameters": {
            "type": "object",
            "properties": {
              "entry_ids": {
                "type": "array",
                "description": "List of entry IDs to select.",
                "items": {
                  "type": "string"
                },
                "minItems": 1,
                "uniqueItems": true
              }
            },
            "required": ["entry_ids"],
            "additionalProperties": false
          }
        }
      },
    """
    entries = schedule.entries or []

    # Normalize and validate entry_ids (tool schema says strings)
    normalized_ids = set()        # type: set[int]
    invalid_entry_ids: List[str] = []

    for raw_id in entry_ids:
        try:
            normalized_ids.add(int(raw_id))
        except (TypeError, ValueError):
            invalid_entry_ids.append(raw_id)

    matched_ids: List[int] = []

    # Apply selection: True for matching IDs, False for others
    for entry in entries:
        if entry.entry_id in normalized_ids:
            entry.is_selected = True
            matched_ids.append(entry.entry_id)
        else:
            entry.is_selected = False

    # Determine which *valid* IDs did not match any entry
    unmatched_ids = normalized_ids.difference(matched_ids)

    return {
        "selected_entry_ids": [str(eid) for eid in matched_ids],
        "not_found_entry_ids": [str(eid) for eid in unmatched_ids],
        "invalid_entry_ids": invalid_entry_ids,
        "total_selected": len(matched_ids),
    }


def _parse_24h_time_to_time(time_str: str) -> time:
    """
    Parse a 24-hour time string like '09:00' or '14:30' to a datetime.time.

    Accepts:
      - 'HH:MM'  (e.g., '09:00', '14:30')
      - 'HH:MM:SS' (e.g., '09:00:00', '14:30:00') for robustness
    """
    time_str = time_str.strip()

    # Try HH:MM, then HH:MM:SS for flexibility
    for fmt in ("%H:%M", "%H:%M:%S"):
        try:
            return datetime.strptime(time_str, fmt).time()
        except ValueError:
            continue

    raise ValueError(f"Invalid 24-hour time format: {time_str!r}. Expected 'HH:MM' or 'HH:MM:SS'.")


def _entry_date_to_date(entry_date_value: Any) -> date:
    """
    Normalize an Entry.entry_date value to a datetime.date.

    Accepts:
      - datetime.date
      - datetime.datetime
      - 'YYYY-MM-DD' string

    Raises ValueError if it cannot be parsed.
    """
    if isinstance(entry_date_value, date) and not isinstance(entry_date_value, datetime):
        return entry_date_value
    if isinstance(entry_date_value, datetime):
        return entry_date_value.date()
    if isinstance(entry_date_value, str):
        # Expect 'YYYY-MM-DD'
        return datetime.strptime(entry_date_value, "%Y-%m-%d").date()

    raise ValueError(f"Unsupported entry_date type: {type(entry_date_value)!r}")


def add_entry(
    schedule: "Schedule",
    date: str,
    start_time: str,
    end_time: str,
    title: str,
    provider: str,
    note: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Add a new appointment entry.

    This will:
      1. Parse the incoming strings into appropriate datetime/date/time types.
      2. Create an Entry instance.
      3. Persist it via `data_store.add_entry`.
      4. Update the in-memory `schedule.entries` if it falls within the current daterange.

    Parameters
    ----------
    schedule : Schedule
        The current Schedule object (mutable, session-scoped).
    date : str
        Date (optionally with time) of the appointment.
        Supported formats:
          - 'YYYY-MM-DD HH:MM:SS' (e.g., '2025-11-03 09:00:00')  # 24-hour clock
          - 'YYYY-MM-DD' (e.g., '2025-11-03')                    # time defaults to 00:00:00
        The time portion is ignored for storage; only the date is used.
    start_time : str
        Start time in 24-hour clock, 'HH:MM' or 'HH:MM:SS' (e.g., '09:00', '14:00').
    end_time : str
        End time in 24-hour clock, 'HH:MM' or 'HH:MM:SS' (e.g., '11:00', '16:30').
        Must be after start_time; a ValueError is raised otherwise.
    title : str
        Short title/subject.
    provider : str
        Provider name.
    note : Optional[str]
        Optional note (context, location, etc.).

    Returns
    -------
    dict
        A summary of the created entry:
        {
            "status": "Complete"
            "entry_id": int,
            "date": "YYYY-MM-DD",
            "start_time": "HH:MM",
            "end_time": "HH:MM",
            "title": str,
            "provider": str,
            "note": str,
            "added_to_current_view": bool
        }

    Raises
    ------
    ValueError
        If the date string cannot be parsed as a supported format,
        or if end_time is not strictly after start_time.
    """
    # 1. Parse date with a forgiving strategy:
    #    - Accept 'YYYY-MM-DD HH:MM:SS'
    #    - Accept 'YYYY-MM-DD' and default time to 00:00:00
    try:
        if len(date) == 10:  # e.g., "2025-11-14"
            dt = datetime.strptime(date, "%Y-%m-%d")
            dt = dt.replace(hour=0, minute=0, second=0)
        else:
            dt = datetime.strptime(date, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        raise ValueError(
            f"Invalid date format: {date!r}. "
            "Expected 'YYYY-MM-DD HH:MM:SS' or 'YYYY-MM-DD'."
        )

    entry_date = dt.date()

    # 2. Parse 24h times to time objects
    try:
        start_t = _parse_24h_time_to_time(start_time)
        end_t = _parse_24h_time_to_time(end_time)
    except ValueError as e:
        # If you prefer to fail hard, replace this `return` with `raise`.
        return {
            "error": str(e)
        }

    if end_t <= start_t:
        raise ValueError("end_time must be strictly after start_time")

    # 3. Create Entry instance (entry_id will be set by DB)
    entry = Entry(
        entry_id=0,  # placeholder; will be overwritten by data_store.add_entry
        entry_date=entry_date,
        start_time=start_t,
        end_time=end_t,
        title=title,
        provider=provider,
        note=note or "",
        is_selected=False,
    )

    # 4. Persist via data_store; this sets entry.entry_id
    new_id = data_store.add_entry(entry)

    return {
        "status": "Complete",
        "entry_id": new_id,
        "date": entry.entry_date.isoformat(),
        # Match the table format: 'HH:MM'
        "start_time": entry.start_time.strftime("%H:%M"),
        "end_time": entry.end_time.strftime("%H:%M"),
        "title": entry.title,
        "provider": entry.provider,
        "note": entry.note,
    }


def delete_by_filter(
    schedule: Schedule,
    provider: Optional[str] = None,
    date: Optional[str] = None,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    title_contains: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Delete schedule entries that match structured criteria (provider, date, date range, title).

    This function:
      - Interprets the filter arguments into an effective date range and text filters.
      - Selects matching entries from the in-memory schedule.entries.
      - Delegates actual deletion to `delete_entries` (DB + in-memory update).
      - Returns the same core summary shape as `delete_entries`, plus debug info.

    Safety:
      - If *no* filters are provided, no entries are deleted and an error is returned.
    """
    # Safety guard: require at least one constraint
    if not any([provider, date, from_date, to_date, title_contains]):
        return {
            "deleted_entry_ids": [],
            "total_deleted": 0,
            "error": "No filters provided. At least one of provider, date, from_date, to_date, or title_contains is required."
        }

    entries = schedule.entries or []

    # --- Normalize filters ----------------------------------------------------
    provider_norm = provider.strip().lower() if isinstance(provider, str) and provider.strip() else None
    title_sub_norm = (
        title_contains.strip().lower()
        if isinstance(title_contains, str) and title_contains.strip()
        else None
    )

    # Determine effective date range filter (optional)
    # If `date` is provided, it overrides from_date/to_date.
    start_date: Optional[date] = None
    end_date: Optional[date] = None

    try:
        if date:
            # Exact single day
            d = datetime.strptime(date.strip(), "%Y-%m-%d").date()
            start_date = d
            end_date = d
        elif from_date or to_date:
            if from_date:
                start_date = datetime.strptime(from_date.strip(), "%Y-%m-%d").date()
            else:
                # default to current view's start
                start_date = schedule.daterange.date_from.date()

            if to_date:
                end_date = datetime.strptime(to_date.strip(), "%Y-%m-%d").date()
            else:
                # default to current view's end
                end_date = schedule.daterange.date_to.date()
        else:
            # No explicit date filter: operate over what's in schedule.entries
            # (which is already scoped by schedule.daterange).
            start_date = None
            end_date = None
    except ValueError as e:
        # Bad date from the tool call; report back instead of deleting the wrong things
        return {
            "deleted_entry_ids": [],
            "total_deleted": 0,
            "error": f"Invalid date filter: {e}"
        }

    # --- Select candidate entries --------------------------------------------
    candidate_ids: List[int] = []

    for entry in entries:
        try:
            entry_day = _entry_date_to_date(entry.entry_date)
        except ValueError:
            # If the entry_date is malformed, skip it rather than risking wrong deletion
            continue

        # Date filter (if any)
        if start_date is not None and end_date is not None:
            if not (start_date <= entry_day <= end_date):
                continue

        # Provider filter (if provided)
        if provider_norm is not None:
            if not entry.provider:
                continue
            if entry.provider.strip().lower() != provider_norm:
                continue

        # Title substring filter (if provided)
        if title_sub_norm is not None:
            if not entry.title:
                continue
            if title_sub_norm not in entry.title.lower():
                continue

        candidate_ids.append(entry.entry_id)

    if not candidate_ids:
        return {
            "deleted_entry_ids": [],
            "total_deleted": 0,
            "matched_filters_but_nothing_found": True,
            "applied_filters": {
                "provider": provider,
                "title_contains": title_contains,
                "date": date,
                "from_date": from_date,
                "to_date": to_date,
            },
        }

    # --- Delegate to existing delete_entries ---------------------------------
    deletion_summary = delete_entries(schedule, candidate_ids)

    # Optionally attach filter info for debugging
    deletion_summary["applied_filters"] = {
        "provider": provider,
        "title_contains": title_contains,
        "date": date,
        "from_date": from_date,
        "to_date": to_date,
    }
    deletion_summary["matched_entry_ids"] = candidate_ids

    return deletion_summary


def delete_entries(
    schedule: Schedule,
    entry_ids: Sequence[Union[int, str]],
) -> Dict[str, Any]:
    """
    Delete specific schedule entries by their entry_id values.

    This function:
      - Finds all entries in `schedule.entries` whose `entry_id` is in `entry_ids`.
      - Deletes each one from the database via `data_store.remove_entry` with user_id=1.
      - Removes them from the in-memory `schedule.entries` list.

    Parameters
    ----------
    schedule : Schedule
        The current Schedule object (mutable, session-scoped).
    entry_ids : Sequence[Union[int, str]]
        The entry_id values for entries to delete. These should come directly
        from the table returned by get_schedule_table.

    Returns
    -------
    dict
        A summary of the deletion:
        {
            "deleted_entry_ids": [int, ...],
            "total_deleted": int
        }
    """
    entries = schedule.entries or []

    # Normalize IDs so we can compare safely whether they come as int or str
    # Assume Entry.entry_id is an int; adjust if your model uses strings.
    normalized_ids: List[int] = []
    for eid in entry_ids:
        if isinstance(eid, int):
            normalized_ids.append(eid)
        else:
            # attempt to parse string IDs to int; ignore ones that can’t be parsed
            try:
                normalized_ids.append(int(eid))
            except (TypeError, ValueError):
                continue

    if not normalized_ids:
        return {
            "deleted_entry_ids": [],
            "total_deleted": 0,
        }

    id_set = set(normalized_ids)

    # Identify entries to delete
    targets: List[Entry] = [e for e in entries if e.entry_id in id_set]
    deleted_ids: List[int] = []

    for entry in targets:
        # Hard-code user_id=1 for this POC
        affected = data_store.remove_entry(entry, user_id=1)
        if affected > 0:
            deleted_ids.append(entry.entry_id)

    # Remove deleted entries from the in-memory schedule
    if deleted_ids:
        remaining = [e for e in entries if e.entry_id not in deleted_ids]
        schedule.entries = remaining

    return {
        "deleted_entry_ids": deleted_ids,
        "total_deleted": len(deleted_ids),
    }
