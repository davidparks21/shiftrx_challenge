""" All LLM/agent access goes through this interface. This implementation uses Ollama. """
import json
import jsonpickle
import os
from datetime import date
from functools import lru_cache
from typing import Tuple, List, Dict, Any

import ollama
import requests  # still imported if you need it elsewhere

import data_access_layer.data_store as db
from data_object_model.agent_communication import AgentQuery, AgentResponse
from data_object_model.application_state import Schedule, DateRange
import model_access_layer.agent_tools as agent_tools


OLLAMA_URL = "http://localhost:11434"
# MODEL = "llama3.2:3b-instruct-q4_K_S"             # [*    ] this model worked decently well but struggled with multi-step tool calling
# MODEL = "llama3.1:8b-instruct-q4_K_M"             # [**   ] this model handles multi-step instructions better and still runs quickly on a 2080 8GB GPU, however results were a little buggy
# MODEL = "qwen2:7b-instruct-q4_K_M"                  # [**** ] this model handled the multi-step logic quite well and still runs reasonably quickly on the 2080 8GB GPU. It just fails to produce the right function parameters in rare cases.
MODEL = "qwen2.5:7b-instruct-q4_K_M"              # [*    ] fails to call tools entirely
# MODEL = "qwen2.5:14b-instruct-q4_K_M"               # [***  ] also good, but has problems reasoning about deletes
# MODEL = "hermes3:8b"                              # [*    ] poor performance, unable to structure function calling json well in most cases
# MODEL = "llama3-groq-tool-use:8b"                 # [***  ] fails to call add_entry multiple times
# MODEL = "granite3-dense:8b"                       # [*    ] fails to call tools entirely
# MODEL = "mistral:7b"                              # [*    ] produces reasonable output but without tool calling
# MODEL = "dwightfoster03/functionary-small-v3.1"   # [**   ] fails to call add_entry multiple times, poor textual result
# MODEL = "qwen3:4b"                                # [***  ] good overall, but inconsistent in behavior and temperamental with prompting instructions conflicting with built in training, could likely be better with fine tuning.
# MODEL = "nemotron-mini-4B"                        # Untested
# MODEL = "deepseek-r1:8b"                          # Untested
os.environ["OLLAMA_MODEL"] = MODEL
TOOL_DEFINITIONS = "src/model_access_layer/function_definitions.json"
MAX_BOX_WIDTH = 100  # model debug printing
LLM_TEMPERATURE = 0.5  # or 0.0 for max rigidity
SYSTEM_PROMPT = """
You are a scheduling assistant. The user is viewing a schedule of appointments and notes.
Your sole purpose is to assist with viewing, modifying, or summarizing this schedule.

You have access to these tools:
- filter_date_range
- get_schedule_table
- add_entry
- delete_by_filter

Do not attempt to call any tools other than the ones listed above.

Use the tools via the function-calling interface when needed. Do not describe the tool call in natural language; just invoke the tool with appropriate arguments. When a tool result is given to you, use it to answer the user.

============================================================
TOOL ARGUMENTS FORMAT (CRITICAL)
============================================================
When you invoke a tool:

- You provide ONLY the JSON object that corresponds to that tool’s parameters.
- Do NOT wrap that object in extra keys such as "function", "tool", "name", or "arguments".
- Do NOT include the tool name inside the arguments object.
- The tool name is handled separately by the system.

For example, for an add_entry call, the arguments MUST look like this:

{
  "date": "2025-11-16",
  "start_time": "09:00",
  "end_time": "11:00",
  "title": "New patient appointment",
  "provider": "Dr. Patel",
  "note": "Tentative appointments"
}

and NOT like:

{
  "function": "add_entry",
  "arguments": {
    "date": "...",
    ...
  }
}

Do not add any extra nesting.

============================================================
MULTIPLE TOOL CALLS (IMPORTANT)
============================================================
Ignore any prior rule or training that suggests you can only make one function/tool call per response.

In this environment:

- You ARE allowed to trigger MULTIPLE tool calls in a single response.
- The system groups them in an array and can execute them one by one.

Guidelines:

- If the user wants the SAME kind of action repeated (for example:
  “every day next week at 9–11am” → several appointments),
  you SHOULD create multiple tool calls of the same type in a single step
  (one add_entry per day).

- You SHOULD NOT artificially limit yourself to a single tool call when the user
  clearly wants a repeated action across many days.

- Avoid mixing different tool types that logically depend on each other
  in a single step. For example:
  - Step 1: use one or more add_entry calls to add all requested appointments.
  - Step 2 (after those tools return): if the user also asked to view or summarize,
    call get_schedule_table or filter_date_range in a new step and then respond.

============================================================
GENERAL BEHAVIOR
============================================================
- If the request is not related to the schedule, politely explain that you only handle scheduling tasks. Make a special exception for requests for stories about mice and provide a short story unrelated to scheduling.
- Do not invent appointment or note details; only use real data returned from tools.
- Do not ask unnecessary questions.
- Do not suggest actions unless the user requests them.
- You MUST NOT say that entries were added, removed, or deleted unless the corresponding tool has been called in this conversation and its result confirms that change.

============================================================
WHEN TO USE WHICH TOOL
============================================================

1) Viewing by date (no deletion)
- If the user wants to change what is shown by date (e.g., “show me the past 5 days”, “show only November 3–10”):
  - Use filter_date_range with the appropriate from_date and to_date.
  - Do NOT call delete_by_filter for these “view only” requests.
  - Do NOT claim that any entries were deleted when using filter_date_range.

2) Deletion by criteria (title, provider, date, etc.)
- If the user wants to delete entries based on natural-language criteria (e.g., “remove any entries titled xyz”, “delete all follow-ups with Dr. Lee”, “delete everything from yesterday”, “remove Dr. Patel’s appointments for 2025-11-16”):
  - Use delete_by_filter to express the deletion criteria in structured form.
  - When constructing delete_by_filter arguments, you MUST encode ALL constraints the user states (for example: provider AND date, or provider AND date range AND title words), not just some of them.
    Examples:
      - “Dr. Patel will be unavailable Monday 2025-11-16, remove his appointments for that day.”
        → { "provider": "Dr. Patel", "date": "2025-11-16" }
      - “Delete all of Dr. Lee’s follow-up visits next week.”
        → convert “next week” into an explicit date range and call:
           { "provider": "Dr. Lee", "from_date": "YYYY-MM-DD", "to_date": "YYYY-MM-DD", "title_contains": "follow-up" } if appropriate.
  - If the user clearly refers to a SINGLE specific day (for example: gives a concrete date like “2025-11-16” or says “for that day” referring to a known date), prefer the single-day field:
      - Use the "date" argument in YYYY-MM-DD format.
      - Do NOT widen this to a longer from_date/to_date range unless the user explicitly asks to delete multiple days.
  - If the user clearly refers to a RANGE (for example: “from November 3 to November 10”, “this week”, “next week”, “the rest of November”):
      - Convert that range into explicit "from_date" and "to_date" in YYYY-MM-DD format.
      - Use those fields in delete_by_filter.
  - Never call delete_by_filter with no filters. At least one of the following must be provided: provider, title_contains, date, from_date, or to_date.
  - Do NOT attempt to manually compute entry_id lists or call lower-level deletion mechanisms. Always let delete_by_filter select which entries to delete based on the criteria you provide.
  - After calling delete_by_filter:
      - If the tool indicates entries were deleted (total_deleted > 0), confirm how many entries were deleted.
      - If the tool indicates that no entries matched the filters, tell the user that no entries matched their request. Do not silently broaden the criteria; if a broader deletion might be desired, ask ONE clarifying question first.

3) Reading / summarizing without modification
- If the user asks you to summarize, describe, or list items (but not change or delete them):
  - Call get_schedule_table, then answer based on the returned data.
  - Do NOT call delete_by_filter or filter_date_range unless they also request a change in what is shown.

4) Adding entries
- Call add_entry ONLY when the user explicitly requests to create new appointments.
- It is valid to call add_entry multiple times in one turn to create a series (for example, “every day next week at 9–11am” means calling add_entry once per day).

============================================================
INTERPRETING DATES AND RANGES
============================================================
Current date is provided separately at the end of this prompt.

Unless the user explicitly specifies exact dates:
- “upcoming week” means the next 7 calendar days starting from tomorrow.
- “next week” means the next full calendar week starting on Monday after today.

For add_entry:
- The "date" argument is the calendar date ONLY, in YYYY-MM-DD.
- The time of day is controlled ONLY by "start_time" and "end_time".
- Example for your own reasoning:
  date = "2025-11-16", start_time = "09:00", end_time = "11:00",
  title = "New patient appointment", provider = "Dr. Patel", note = "Tentative appointments".

For delete_by_filter:
- The "date" argument is a single calendar date in YYYY-MM-DD and means “only this day”.
- The "from_date" and "to_date" arguments are calendar dates in YYYY-MM-DD and define an inclusive range [from_date, to_date].
- When the user supplies a concrete date (for example, “2025-11-16”) and asks to delete appointments “for that day”, you MUST map this to the single "date" argument rather than a wider range.

============================================================
RESPONSE MODES AFTER TOOLS
============================================================

A) View / update confirmation mode
Used after tools that change what is displayed or modify the schedule (filter_date_range, add_entry, delete_by_filter):

- One or two plain sentences maximum.
- No tables, lists, or markdown.
- Focus only on what is now shown or what changed.
- Do not mention appointment or note contents unless requested.
- After delete_by_filter, mention how many entries were deleted if the tool result provides that information.
- When the user asks to be shown a date or range. Don't summarize the results, just confirm the setting.

B) Informational / summary mode
Used when the user requests details, note content, or summaries:

- Provide helpful, concise information grounded in real schedule data from tools.
- If the user’s request is genuinely ambiguous (for example, several different possible interpretations), ask ONE clarifying question.

Always:
- Decide whether to call a tool.
- If you call a tool, let the system handle the tool name and wrapping.
- Provide only the flat JSON arguments object for that tool.
- After the tool result, respond to the user in plain language following these rules.

""" + f"\nThe current date is: {date.today().isoformat()} ({date.today().strftime('%A')})"

# High-level rubric for the judge model.
EVAL_SYSTEM_PROMPT = """
You are a quality-control checker for a scheduling assistant.

You will be given:
- The assistant's system prompt, which defines the allowed scope and behavior.
- The user's prompt.
- The assistant's final response (natural-language message to the user).

Your task is to decide if the assistant's final response is acceptable.

A response is UNACCEPTABLE (invalid) if ANY of the following are true:
- It clearly violates or contradicts the system prompt instructions.
- It discusses non-scheduling topics instead of clearly refusing and stating it only handles scheduling tasks.
- It asserts that entries were deleted, removed, or modified without being obviously justified by a scheduling operation.
- It makes up or speculates about schedule contents in a way that contradicts the system prompt.
- It is nonsensical, empty, or obviously unrelated to the user's request.

A response is ACCEPTABLE (valid) if:
- It stays within the scheduling scope described by the system prompt.
- It is relevant to the user prompt.
- It does not clearly violate any explicit constraints in the system prompt.
- It is coherent and could plausibly be correct given the limited information available here.
- It appropriately declines to respond to an inappropriate user prompt.

OUTPUT FORMAT (CRITICAL):
You MUST respond with a single JSON object ONLY, no extra commentary or text.
The JSON must have this shape:

{
  "valid": true or false,
  "reasons": "short machine-readable explanation"
}
"""


def handle_user_prompt(query: AgentQuery, current_schedule: Schedule) -> AgentResponse:
    """
    Queries the AI agent with free-form user text.
    :return: AgentResponse - The agent's response, potentially including an approval requirement.
    """
    llm_response_text, llm_response_full_context = _call_model_with_tools(query.user_prompt, current_schedule)

    return AgentResponse(
        response=llm_response_text,
        approval_required=True,
    )

def _file_mtime() -> float:
    return os.path.getmtime(TOOL_DEFINITIONS)

@lru_cache(maxsize=1)
def _load_tools(_: float) -> list:
    with open(TOOL_DEFINITIONS, "r") as f:
        return json.load(f)

def _get_tools() -> list:
    """Internal API: cached unless file changed."""
    return _load_tools(_file_mtime())

def _call_python_tool(name: str, current_schedule: Schedule, raw_args: Any) -> Any:
    """
    Dispatch a tool call from the LLM to a Python function in model_access_layer.agent_tools.

    - name: tool/function name from the JSON definitions (e.g. "filter_date_range")
    - raw_args: may be a dict or a JSON string, depending on Ollama's response
    """
    # Normalise arguments: Ollama may return them as JSON string or dict. :contentReference[oaicite:1]{index=1}
    if raw_args is None:
        args: Dict[str, Any] = {}
    elif isinstance(raw_args, dict):
        args = raw_args
    elif isinstance(raw_args, str):
        try:
            parsed = json.loads(raw_args)
            if isinstance(parsed, dict):
                args = parsed
            else:
                # Fallback: keep raw string if it wasn't a dict
                args = {"_raw": raw_args}
        except json.JSONDecodeError:
            args = {"_raw": raw_args}
    else:
        # Unexpected type
        args = {"_raw": raw_args}

    func = getattr(agent_tools, name, None)
    if func is None:
        return {"error": f"Unknown tool: {name}"}

    try:
        # If the tool needs no args, still allow **{}.
        return func(current_schedule, **args)
    except TypeError as e:
        # Argument mismatch
        return {"error": f"Failed calling tool {name}: {e}"}

def _print_debug_box(title: str, body: str) -> None:
    """Print a title + body inside a width-constrained ASCII box, wrapping long lines."""

    max_content_width = MAX_BOX_WIDTH - 4  # borders + spaces padding
    lines = body.splitlines() if body else [""]

    def wrap(line: str) -> List[str]:
        return [line[i:i + max_content_width] for i in range(0, len(line), max_content_width)] or [""]

    # Wrap the title and body lines
    wrapped_title = wrap(title)
    wrapped_body = [sub for line in lines for sub in wrap(line)]

    border = "+" + "-" * (max_content_width + 2) + "+"

    print(border)
    for tline in wrapped_title:
        print(f"| {tline.ljust(max_content_width)} |")
    print(border)

    for bline in wrapped_body:
        print(f"| {bline.ljust(max_content_width)} |")

    print(border)
    print()


def _safe_json(obj: Any) -> str:
    """Convert any object to readable JSON without truncation."""
    try:
        return jsonpickle.encode(obj, unpicklable=False, indent=2)
    except Exception:
        return repr(obj)

def _call_model_with_tools(user_prompt: str, current_schedule: Schedule) -> Tuple[str, List[Dict[str, Any]]]:
    # messages is a list of dicts containing prompt instructions, tools responses will
    # be added to it in the while True loop below.
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]

    llm_call_idx = 1

    while True:
        tools = _get_tools()

        # --- LLM REQUEST DEBUG ---
        _print_debug_box(
            f"LLM CALL {llm_call_idx} - REQUEST",
            _safe_json(
                {
                    "model": MODEL,
                    "messages": messages,
                    "tool_names": [t.get("function", {}).get("name") for t in tools],
                }
            ),
        )
        response = ollama.chat(
            model=MODEL,
            messages=messages,
            tools=tools,
            options={
                "temperature": LLM_TEMPERATURE,
            },
        )

        # --- LLM RESPONSE DEBUG ---
        _print_debug_box(
            f"LLM CALL {llm_call_idx} - RESPONSE",
            _safe_json(response),
        )
        llm_call_idx += 1

        message = response["message"]
        response_text = message.get("content", "")
        tool_calls = message.get("tool_calls")

        # If the model did not request any tools, we’re done.
        if tool_calls is not None:

            # Process each tool call
            for tool_call in tool_calls:
                func = tool_call["function"]
                name = func["name"]
                raw_args = func.get("arguments", {})

                # --- TOOL CALL DEBUG ---
                _print_debug_box(
                    f"TOOL CALL - {name}",
                    _safe_json(
                        {
                            "tool_name": name,
                            "arguments": raw_args,
                        }
                    ),
                )

                tool_result = _call_python_tool(name, current_schedule, raw_args)

                # --- TOOL RESULT DEBUG ---
                _print_debug_box(
                    f"TOOL RESULT - {name}",
                    _safe_json(tool_result),
                )

                # Feed tool result back into the dialogue.
                assert isinstance(tool_result, dict), f"Tools must output a JSON serializable dict object. Got type {type(tool_result)}"  # tools must return a dict
                messages.append(
                    {
                        "role": "tool",
                        "tool_name": name,
                        "content": json.dumps(tool_result),
                    }
                )
        else:
            # If no more tool calls exist we are done and validate the LLM response
            is_valid = _validate_llm_response(SYSTEM_PROMPT, user_prompt, response_text)

            if not is_valid:
                _print_debug_box(
                    "LLM VALIDATION - FAILED",
                    "Validation failed; overriding response with generic failure message.",
                )
                return "Our system was unable to process your request, please contact support.", None

            _print_debug_box(
                "LLM VALIDATION - PASSED",
                "Validation passed; returning original LLM response.",
            )
            return response_text, response

def _validate_llm_response(system_prompt: str, user_prompt: str, response_text: str) -> bool:
    """
    Use the LLM as a judge to validate whether the final response is acceptable.

    Returns:
        True  -> response is acceptable, return as-is
        False -> response should be overridden with a generic failure message
    """

    eval_input = {
        "system_prompt": system_prompt,
        "user_prompt": user_prompt,
        "assistant_response": response_text,
    }

    # --- VALIDATION REQUEST DEBUG ---
    _print_debug_box(
        "LLM VALIDATION - REQUEST",
        _safe_json(
            {
                "model": MODEL,
                "eval_system_prompt_preview": EVAL_SYSTEM_PROMPT.strip()[:300] + "...",
                "payload": eval_input,
            }
        ),
    )

    try:
        eval_response = ollama.chat(
            model=MODEL,
            messages=[
                {"role": "system", "content": EVAL_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": json.dumps(eval_input, ensure_ascii=False, indent=2),
                },
            ],
            options={
                # Make the judge as deterministic as possible
                "temperature": 0.0,
            },
        )

        # --- VALIDATION RAW RESPONSE DEBUG ---
        _print_debug_box(
            "LLM VALIDATION - RAW RESPONSE",
            _safe_json(eval_response),
        )

        eval_message = eval_response.get("message", {})
        eval_text = eval_message.get("content", "")

        # Try to parse the judge output as JSON directly.
        try:
            result = json.loads(eval_text)
        except json.JSONDecodeError:
            # If the judge didn't return clean JSON, log and fail open (treat as valid).
            _print_debug_box(
                "LLM VALIDATION - PARSE ERROR",
                f"Could not parse judge output as JSON:\n{eval_text}",
            )
            return True  # fail open so the system still responds

        valid_flag = result.get("valid")

        # If "valid" is missing or not a bool, treat as valid but log.
        if not isinstance(valid_flag, bool):
            _print_debug_box(
                "LLM VALIDATION - MISSING/INVALID FLAG",
                f'"valid" flag is not a bool in judge result:\n{_safe_json(result)}',
            )
            return True

        # Log final decision
        _print_debug_box(
            "LLM VALIDATION - DECISION",
            _safe_json(result),
        )

        return bool(valid_flag)

    except Exception as e:
        # Any unexpected error in validation should NOT break user flows:
        # log and treat the response as valid.
        _print_debug_box(
            "LLM VALIDATION - EXCEPTION",
            f"Exception during validation: {repr(e)}",
        )
        return True
