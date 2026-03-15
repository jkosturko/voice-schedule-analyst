"""HTTP server for Cloud Run — serves the Schedule Analyst agent via REST endpoints.

Also supports ADK's `adk web` / `adk api_server` via the root_agent export in schedule_analyst/agent.py.
This file provides webhook-compatible endpoints for Athena integration + health checks.
"""

import os
import json
import logging
import functools

from flask import Flask, request, jsonify, send_from_directory, Response
from google import genai

from schedule_analyst.calendar_tools import get_calendar_events, find_conflicts

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
app = Flask(__name__, static_folder=STATIC_DIR)

# ── Password protection (Cloud Run only) ──
# Set APP_PASSWORD env var on Cloud Run to enable.
# Not set locally → no password required.
APP_PASSWORD = os.environ.get("APP_PASSWORD")


def check_auth(username, password):
    return password == APP_PASSWORD


def authenticate():
    return Response(
        "Access denied. Please provide credentials.", 401,
        {"WWW-Authenticate": 'Basic realm="Schedule Analyst"'},
    )


def requires_auth(f):
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        if not APP_PASSWORD:
            return f(*args, **kwargs)  # No password set → open access (local dev)
        auth = request.authorization
        if not auth or not check_auth(auth.username, auth.password):
            return authenticate()
        return f(*args, **kwargs)
    return decorated


@app.route("/", methods=["GET"])
@requires_auth
def index():
    """Serve the Gemini Live UI."""
    return send_from_directory(STATIC_DIR, "index.html")


@app.route("/api", methods=["GET"])
@requires_auth
def api_index():
    """API info — available endpoints."""
    return jsonify({
        "name": "Voice Schedule Analyst",
        "description": "AI-powered voice schedule analysis using Gemini Live API + Google Calendar",
        "endpoints": {
            "GET /": "Interactive UI",
            "GET /api": "This page",
            "GET /health": "Health check",
            "GET /health/gemini": "Verify Gemini API connection",
            "POST /schedule-analyst/analyze": "Analyze schedule for conflicts and patterns",
            "POST /schedule-analyst/optimize": "Get optimization suggestions",
            "POST /schedule-analyst/question": "Ask a question about your schedule",
        },
        "voice": "python -m schedule_analyst voice",
        "text": "python -m schedule_analyst text",
        "framework": "Google ADK + Gemini Live API",
    })


@app.route("/health", methods=["GET"])
def health():
    """Health check endpoint for Cloud Run."""
    return jsonify({
        "status": "healthy",
        "agent": "schedule-analyst",
        "version": "0.1.0",
        "framework": "google-adk",
    })


@app.route("/health/gemini", methods=["GET"])
def health_gemini():
    """Verify Gemini API key works — generates a one-line response."""
    try:
        client = genai.Client()
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents="Say 'Gemini is connected' in exactly 4 words.",
        )
        return jsonify({
            "status": "connected",
            "model": "gemini-2.0-flash",
            "response": response.text.strip(),
        })
    except Exception as e:
        logger.error("[GEMINI_HEALTH_ERROR] %s", e)
        return jsonify({"status": "error", "error": str(e)}), 500


@app.route("/schedule-analyst/analyze", methods=["POST"])
@requires_auth
def analyze():
    """Analyze schedule — find conflicts, gaps, back-to-back warnings."""
    data = request.get_json(silent=True) or {}
    time_range = data.get("time_range", "this week")

    events_result = get_calendar_events(time_range=time_range)
    if events_result.get("error"):
        logger.error("[ANALYZE_ERROR] %s", events_result["error"])
        return jsonify({"error": events_result["error"]}), 500

    conflicts_result = find_conflicts(time_range=time_range)

    summary = _generate_summary(
        events_result,
        conflicts_result,
        f"Analyze the user's schedule for {time_range}. Report conflicts first, then gaps, then back-to-back meeting warnings. Be conversational and concise.",
    )

    return jsonify({
        "conflicts": conflicts_result.get("conflicts", []),
        "back_to_back": conflicts_result.get("back_to_back_warnings", []),
        "dead_time": conflicts_result.get("dead_time_gaps", []),
        "summary": summary,
        "event_count": events_result.get("count", 0),
    })


@app.route("/schedule-analyst/optimize", methods=["POST"])
@requires_auth
def optimize():
    """Suggest schedule optimizations."""
    data = request.get_json(silent=True) or {}
    focus = data.get("focus", "general")

    events_result = get_calendar_events(time_range="this week")
    if events_result.get("error"):
        logger.error("[OPTIMIZE_ERROR] %s", events_result["error"])
        return jsonify({"error": events_result["error"]}), 500

    conflicts_result = find_conflicts(time_range="this week")

    summary = _generate_summary(
        events_result,
        conflicts_result,
        f"Suggest specific schedule optimizations focused on: {focus}. Include actionable verbs (move, shift, block, protect, cancel, reschedule, add). Be specific about which events to change.",
    )

    return jsonify({
        "suggestions": summary,
        "focus": focus,
        "event_count": events_result.get("count", 0),
    })


@app.route("/schedule-analyst/question", methods=["POST"])
@requires_auth
def question():
    """Answer a natural language question about the schedule."""
    data = request.get_json(silent=True) or {}
    q = data.get("question", "")
    if not q:
        return jsonify({"error": "question is required"}), 400

    events_result = get_calendar_events(time_range="this week")
    calendar_error = events_result.get("error")
    if calendar_error:
        logger.warning("[QUESTION_CALENDAR_WARN] %s — answering without calendar data", calendar_error)

    summary = _generate_summary(
        events_result,
        None,
        f"Answer this question about the user's schedule: {q}. Be conversational and specific."
        + (" Note: Calendar data is unavailable — answer generally." if calendar_error else ""),
    )

    return jsonify({
        "answer": summary,
        "question": q,
        "event_count": events_result.get("count", 0),
        "calendar_connected": not bool(calendar_error),
    })


def _generate_summary(events_result: dict, conflicts_result: dict | None, prompt: str) -> str:
    """Use Gemini to generate a natural-language spoken summary from structured data."""
    try:
        client = genai.Client()

        events = events_result.get("events", [])
        events_text = "\n".join(
            f"- {e['summary']}: {e['start']} to {e['end']}" + (f" at {e['location']}" if e.get('location') else "")
            for e in events
        ) if events else "No events found."

        conflicts_text = "None"
        b2b_text = "None"
        dead_text = "None"
        if conflicts_result:
            if conflicts_result.get("conflicts"):
                conflicts_text = json.dumps(conflicts_result["conflicts"], indent=2)
            if conflicts_result.get("back_to_back_warnings"):
                b2b_text = json.dumps(conflicts_result["back_to_back_warnings"], indent=2)
            if conflicts_result.get("dead_time_gaps"):
                dead_text = json.dumps(conflicts_result["dead_time_gaps"], indent=2)

        full_prompt = f"""{prompt}

## Calendar Events
{events_text}

## Conflicts Found
{conflicts_text}

## Back-to-Back Meeting Blocks
{b2b_text}

## Dead Time Gaps
{dead_text}

Respond in natural, spoken language. No JSON. No bullet points unless explicitly asked. Keep it under 30 seconds of speaking time (~75 words)."""

        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=full_prompt,
        )
        return response.text

    except Exception as e:
        logger.error("[SUMMARY_GEN_ERROR] %s", e)
        event_count = events_result.get("count", 0)
        conflict_count = len(conflicts_result.get("conflicts", [])) if conflicts_result else 0
        return f"You have {event_count} events. I found {conflict_count} conflicts. Check the detailed data for more."


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    logger.info("Starting Schedule Analyst on port %d", port)
    app.run(host="0.0.0.0", port=port, debug=False)
