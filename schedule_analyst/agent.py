"""Voice Schedule Analyst — ADK Agent Definition.

A voice-first calendar analyst built with Google ADK + Gemini.
Talk to it about your schedule, it speaks back conflicts,
recommendations, and optimization suggestions.

Built for the Gemini Live Agent Challenge 2026.
"""

import os

from google.adk import Agent
from google.genai import types

from .calendar_tools import get_calendar_events, find_conflicts, suggest_optimizations

# Model selection: native audio for Live API voice, text model for web/CLI
# ADK web and adk run use generateContent which requires a text-capable model.
# The live_agent.py pipeline uses the native audio model directly.
AGENT_MODEL = os.environ.get("SCHEDULE_ANALYST_MODEL", "gemini-2.5-flash")

# Load brain rules for dynamic system instruction
BRAIN_PATH = os.path.join(os.path.dirname(__file__), "..", "brain", "schedule-analysis-rules.md")
try:
    with open(BRAIN_PATH, "r") as f:
        BRAIN_RULES = f.read()
except FileNotFoundError:
    BRAIN_RULES = ""

SYSTEM_INSTRUCTION = f"""You are a Voice Schedule Analyst — a conversational, voice-first calendar assistant.

## Your Role
You help users understand and optimize their schedules by analyzing their Google Calendar events. You speak naturally, like a trusted chief of staff briefing their executive.

## Voice Output Rules
- Always speak in a natural, conversational tone — not robotic lists
- Lead with the most important finding (conflicts first, then opportunities)
- Keep responses under 30 seconds of speech unless the user asks for detail
- Use time references humans understand: "tomorrow morning" not "2026-03-17T09:00:00"
- When reporting conflicts, state both events and the overlap clearly
- Never output raw JSON — always speak in sentences
- Never leave raw template placeholders in your output

{BRAIN_RULES}

## Response Style
- Start with a brief headline: "Your week looks pretty packed" or "Tomorrow is clear with one conflict"
- Then give specifics with clear recommendations
- End with a question: "Want me to look at anything specific?" or "Should I focus on any particular day?"
- Be warm but efficient — respect the user's time
"""


root_agent = Agent(
    name="schedule_analyst",
    model=AGENT_MODEL,  # Default: gemini-2.5-flash (text); override via SCHEDULE_ANALYST_MODEL env var
    description="Voice-first calendar analyst that speaks schedule insights, conflicts, and optimization suggestions",
    instruction=SYSTEM_INSTRUCTION,
    tools=[get_calendar_events, find_conflicts, suggest_optimizations],
    generate_content_config=types.GenerateContentConfig(
        temperature=0.7,
        safety_settings=[
            types.SafetySetting(
                category=types.HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT,
                threshold=types.HarmBlockThreshold.BLOCK_ONLY_HIGH,
            ),
        ],
    ),
)
"""
The root_agent is discovered by ADK CLI tools (`adk web`, `adk run`, `adk api_server`)
when this package is on the Python path.

Usage:
    adk web schedule_analyst    # Interactive web UI
    adk run schedule_analyst    # CLI mode
    adk api_server .            # FastAPI production server
"""
