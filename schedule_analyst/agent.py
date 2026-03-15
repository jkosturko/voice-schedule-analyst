"""Voice Schedule Analyst — ADK Agent Definition.

A voice-first calendar analyst built with Google ADK + Gemini.
Talk to it about your schedule, it speaks back conflicts,
recommendations, and optimization suggestions.

Built for the Gemini Live Agent Challenge 2026.
"""

import contextlib
import os

from google.adk import Agent
from google.adk.models.google_llm import Gemini
from google.adk.models.llm_request import LlmRequest
from google.adk.models.base_llm import BaseLlmConnection
from google.genai import types

from .calendar_tools import (
    get_calendar_events, find_conflicts, suggest_optimizations,
    update_event, delete_event, create_event,
)

# Model config: text model for generateContent, native audio for bidiGenerateContent (Live API)
# No single model supports both — gemini-2.5-flash supports text, native-audio supports live.
TEXT_MODEL = os.environ.get("SCHEDULE_ANALYST_MODEL", "gemini-2.5-flash")
LIVE_MODEL = os.environ.get("SCHEDULE_ANALYST_LIVE_MODEL", "gemini-2.5-flash-native-audio-latest")


class DualModelGemini(Gemini):
    """Gemini model that uses different models for text vs live (voice) mode.

    generateContent uses TEXT_MODEL (gemini-2.5-flash).
    bidiGenerateContent uses LIVE_MODEL (gemini-2.5-flash-native-audio-latest).
    """

    live_model: str = LIVE_MODEL

    @contextlib.asynccontextmanager
    async def connect(self, llm_request: LlmRequest) -> BaseLlmConnection:
        """Override connect to swap in the native audio model for live sessions."""
        original_model = llm_request.model
        llm_request.model = self.live_model
        try:
            async with super().connect(llm_request) as connection:
                yield connection
        finally:
            llm_request.model = original_model


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

## Calendar Actions
You can READ events, FIND conflicts, and SUGGEST optimizations. You can also WRITE to the calendar:
- **update_event**: Move or rename an existing event (requires event_id from get_calendar_events)
- **delete_event**: Remove a duplicate or cancelled event (requires event_id)
- **create_event**: Add a new block (focus time, packing, transit, buffer breaks)

## Fuzzy Match & Confirm Before Mutating (MANDATORY)
When the user asks to modify, delete, or move an event using a casual name (e.g., "delete the dentist thing", "move team bowling to next week"):
1. First call get_calendar_events to find events that match the user's description
2. Fuzzy match: "dentist thing" → "Dental Appointment", "team bowling" → "Team Bowling Night"
3. If multiple events could match, list them and ask which one
4. **Always confirm before executing any mutation**: "I found 'Dental Appointment' on Tuesday at 2 PM. Should I delete it?"
5. Wait for the user to say yes/confirm before calling update_event, delete_event, or create_event
6. After executing, confirm what you did: "Done — deleted Dental Appointment from Tuesday."

Never execute a calendar mutation without explicit user confirmation. Reading events does not require confirmation.

## Response Style
- Start with a brief headline: "Your week looks pretty packed" or "Tomorrow is clear with one conflict"
- Then give specifics with clear recommendations
- End with a question: "Want me to look at anything specific?" or "Should I focus on any particular day?"
- Be warm but efficient — respect the user's time
"""


root_agent = Agent(
    name="schedule_analyst",
    model=DualModelGemini(
        model=TEXT_MODEL,      # generateContent (text chat in ADK web)
        live_model=LIVE_MODEL,  # bidiGenerateContent (voice/mic in ADK web)
        speech_config=types.SpeechConfig(
            voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(
                    voice_name="Kore"  # Warm, professional voice
                )
            )
        ),
    ),
    description="Voice-first calendar analyst that speaks schedule insights, conflicts, and optimization suggestions",
    instruction=SYSTEM_INSTRUCTION,
    tools=[
        get_calendar_events, find_conflicts, suggest_optimizations,
        update_event, delete_event, create_event,
    ],
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
