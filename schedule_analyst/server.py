"""Custom server entry point — extends ADK's FastAPI with our custom UI + Flask-like endpoints.

Used by Cloud Run Dockerfile CMD to serve both the ADK agent API and our custom Schedule Analyst UI.
"""

import os
import json
import logging

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles

from google import genai
from google.genai import types
from google.adk.cli.fast_api import get_fast_api_app

from .calendar_tools import get_calendar_events, find_conflicts

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Paths
AGENT_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(AGENT_DIR, "static")
PARENT_DIR = os.path.dirname(AGENT_DIR)


def create_app() -> FastAPI:
    """Create FastAPI app that merges ADK agent server with our custom UI."""

    # Create the ADK FastAPI app (handles /run_sse, /run_live, sessions, etc.)
    app = get_fast_api_app(
        agents_dir=PARENT_DIR,  # Parent dir containing schedule_analyst/
        session_service_uri="memory://",
        artifact_service_uri="memory://",
        web=False,  # Don't mount the default dev-ui — we serve our own
        allow_origins=["*"],
    )

    # ── Custom routes (our Schedule Analyst UI + API) ──

    @app.get("/", response_class=HTMLResponse)
    async def index():
        """Serve our custom Schedule Analyst UI."""
        index_path = os.path.join(STATIC_DIR, "index.html")
        if os.path.exists(index_path):
            return FileResponse(index_path, media_type="text/html")
        return HTMLResponse("<h1>Schedule Analyst</h1><p>static/index.html not found</p>")

    @app.get("/health")
    async def health():
        return JSONResponse({
            "status": "healthy",
            "agent": "schedule-analyst",
            "version": "0.1.0",
            "framework": "google-adk",
            "mode": "adk-cloud-run",
        })

    @app.get("/health/gemini")
    async def health_gemini():
        try:
            client = genai.Client()
            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents="Say 'Gemini is connected' in exactly 4 words.",
            )
            return JSONResponse({
                "status": "connected",
                "model": "gemini-2.5-flash",
                "response": response.text.strip(),
            })
        except Exception as e:
            logger.error("[GEMINI_HEALTH_ERROR] %s", e)
            return JSONResponse({"status": "error", "error": str(e)}, status_code=500)

    @app.post("/schedule-analyst/analyze")
    async def analyze(request: Request):
        data = await request.json() if request.headers.get("content-type") == "application/json" else {}
        time_range = data.get("time_range", "this week")

        events_result = get_calendar_events(time_range=time_range)
        if events_result.get("error"):
            logger.error("[ANALYZE_ERROR] %s", events_result["error"])
            return JSONResponse({"error": events_result["error"]}, status_code=500)

        conflicts_result = find_conflicts(time_range=time_range)

        summary = _generate_summary(
            events_result,
            conflicts_result,
            f"Analyze the user's schedule for {time_range}. Report conflicts first, then gaps, then back-to-back meeting warnings. Be conversational and concise.",
        )

        return JSONResponse({
            "conflicts": conflicts_result.get("conflicts", []),
            "back_to_back": conflicts_result.get("back_to_back_warnings", []),
            "dead_time": conflicts_result.get("dead_time_gaps", []),
            "summary": summary,
            "event_count": events_result.get("count", 0),
        })

    @app.post("/schedule-analyst/optimize")
    async def optimize(request: Request):
        data = await request.json() if request.headers.get("content-type") == "application/json" else {}
        focus = data.get("focus", "general")

        events_result = get_calendar_events(time_range="this week")
        if events_result.get("error"):
            return JSONResponse({"error": events_result["error"]}, status_code=500)

        conflicts_result = find_conflicts(time_range="this week")

        summary = _generate_summary(
            events_result,
            conflicts_result,
            f"Suggest specific schedule optimizations focused on: {focus}. Include actionable verbs. Be specific.",
        )

        return JSONResponse({
            "suggestions": summary,
            "focus": focus,
            "event_count": events_result.get("count", 0),
        })

    @app.post("/schedule-analyst/question")
    async def question(request: Request):
        data = await request.json() if request.headers.get("content-type") == "application/json" else {}
        q = data.get("question", "")
        if not q:
            return JSONResponse({"error": "question is required"}, status_code=400)

        events_result = get_calendar_events(time_range="this week")
        calendar_error = events_result.get("error")
        if calendar_error:
            logger.warning("[QUESTION_CALENDAR_WARN] %s", calendar_error)

        summary = _generate_summary(
            events_result,
            None,
            f"Answer this question about the user's schedule: {q}. Be conversational and specific."
            + (" Note: Calendar data is unavailable — answer generally." if calendar_error else ""),
        )

        return JSONResponse({
            "answer": summary,
            "question": q,
            "event_count": events_result.get("count", 0),
            "calendar_connected": not bool(calendar_error),
        })

    return app


def _generate_summary(events_result: dict, conflicts_result: dict | None, prompt: str) -> str:
    """Use Gemini to generate a natural-language summary from structured data."""
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
            config=types.GenerateContentConfig(
                thinking_config=types.ThinkingConfig(thinking_budget=0),
                temperature=0.7,
            ),
        )
        return response.text

    except Exception as e:
        logger.error("[SUMMARY_GEN_ERROR] %s", e)
        event_count = events_result.get("count", 0)
        conflict_count = len(conflicts_result.get("conflicts", [])) if conflicts_result else 0
        return f"You have {event_count} events. I found {conflict_count} conflicts. Check the detailed data for more."


# Create app instance for uvicorn
app = create_app()
