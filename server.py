"""Unified ADK + Static server for Cloud Run deployment.

Replaces the Flask app (main.py) with ADK's FastAPI server,
serving the custom UI alongside the full agent (voice + text + tools).
"""

import os
import logging
import functools
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from starlette.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from google.adk.cli.fast_api import get_fast_api_app
from google import genai

logger = logging.getLogger(__name__)

# ── Auth middleware ──
APP_PASSWORD = os.environ.get("APP_PASSWORD")

class BasicAuthMiddleware(BaseHTTPMiddleware):
    """Basic auth middleware — only active when APP_PASSWORD is set."""

    OPEN_PATHS = {"/health", "/health/gemini"}

    async def dispatch(self, request: Request, call_next):
        # No password configured → open access (local dev)
        if not APP_PASSWORD:
            return await call_next(request)

        # Health endpoints are always open
        if request.url.path in self.OPEN_PATHS:
            return await call_next(request)

        # Check Basic Auth
        auth = request.headers.get("Authorization")
        if auth and auth.startswith("Basic "):
            import base64
            decoded = base64.b64decode(auth[6:]).decode("utf-8")
            _, _, password = decoded.partition(":")
            if password == APP_PASSWORD:
                return await call_next(request)

        return Response(
            content="Access denied. Please provide credentials.",
            status_code=401,
            headers={"WWW-Authenticate": 'Basic realm="Schedule Analyst"'},
        )

# ── Calendar ID assertion ──
CALENDAR_ID = os.environ.get(
    "GOOGLE_CALENDAR_ID",
    "556107517e83bcf5c9a7273f25bff29b2a6aff526d8ad1c5680a862f5831bf4a@group.calendar.google.com"
)
if CALENDAR_ID == "primary":
    logger.warning(
        "[STARTUP] GOOGLE_CALENDAR_ID is set to 'primary'. "
        "This may expose personal calendar data on public URLs."
    )
else:
    logger.info("[STARTUP] Using calendar ID: %s", CALENDAR_ID[:20] + "...")

# ── Build the app ──
STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")

app = get_fast_api_app(
    agents_dir=os.path.dirname(os.path.abspath(__file__)),
    session_service_uri="sqlite:///./sessions.db",
    allow_origins=["*"],
    web=False,  # We serve our own UI, not ADK's built-in
)

# Add auth middleware
app.add_middleware(BasicAuthMiddleware)

# ── Custom health endpoints ──
@app.get("/health")
async def health():
    return {"status": "healthy", "agent": "schedule-analyst", "version": "0.2.0", "server": "adk-fastapi"}

@app.get("/health/gemini")
async def health_gemini():
    try:
        client = genai.Client()
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents="Say 'Gemini is connected' in exactly 4 words.",
        )
        return {"status": "connected", "model": "gemini-2.5-flash", "response": response.text.strip()}
    except Exception as e:
        logger.error("[GEMINI_HEALTH_ERROR] %s", e)
        return JSONResponse({"status": "error", "error": str(e)}, status_code=500)

# ── Serve custom UI (MUST be last — catch-all for static files) ──
app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
