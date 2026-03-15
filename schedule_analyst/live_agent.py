"""Gemini Live API integration for real-time voice interaction.

This module provides the voice interface using Gemini's Live API
for real-time audio streaming. The user speaks, the agent listens,
queries the calendar, and speaks back analysis.
"""

import asyncio
import json
import sys

from google import genai
from google.genai import types

from .calendar_tools import get_calendar_events, find_conflicts, suggest_optimizations

# Tool declarations for the Live API (function calling)
TOOL_DECLARATIONS = types.Tool(
    function_declarations=[
        types.FunctionDeclaration(
            name="get_calendar_events",
            description="Fetch calendar events for a time range. Use this when the user asks about their schedule, what's coming up, or what their day/week looks like.",
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "time_range": types.Schema(
                        type=types.Type.STRING,
                        description="Time range: 'today', 'tomorrow', 'this week', 'next week', 'next 3 days', 'next 7 days'",
                    ),
                },
            ),
        ),
        types.FunctionDeclaration(
            name="find_conflicts",
            description="Find scheduling conflicts, overlapping events, back-to-back meeting chains, and dead time gaps. Use when the user asks about conflicts, overlaps, or schedule problems.",
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "time_range": types.Schema(
                        type=types.Type.STRING,
                        description="Time range to check for conflicts",
                    ),
                },
            ),
        ),
        types.FunctionDeclaration(
            name="suggest_optimizations",
            description="Suggest specific schedule optimizations — moves, shifts, blocks — based on analysis rules. Use when the user asks for recommendations, how to improve their schedule, or what to change.",
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "focus": types.Schema(
                        type=types.Type.STRING,
                        description="What to optimize for: 'deep work', 'meeting consolidation', 'travel prep', 'general'",
                    ),
                },
            ),
        ),
    ]
)

SYSTEM_INSTRUCTION = """You are a Voice Schedule Analyst — a conversational, voice-first calendar assistant.

You help users understand and optimize their schedules by analyzing their Google Calendar events. You speak naturally, like a trusted chief of staff briefing their executive.

Voice Output Rules:
- Speak naturally and conversationally — not robotic lists
- Lead with the most important finding (conflicts first, then opportunities)
- Keep responses concise — under 30 seconds unless asked for detail
- Use human time references: "tomorrow morning" not ISO timestamps
- When reporting conflicts, clearly state both events and the overlap
- Never output raw JSON — speak in sentences
- Be warm but efficient

Schedule Analysis Rules:
1. Creative blocks (Deep Work, Focus Time) are PROTECTED — never suggest removing them
2. Triple-bookings are critical, double-bookings are warnings
3. Travel events need 1.5 hour buffer before departure
4. 3+ back-to-back meetings trigger a meeting fatigue warning
5. Gaps under 30 minutes between meetings are dead time
6. Morning routines before 9am are protected
7. Family events take priority over moveable work events

Always end with an offer to dig deeper: "Want me to look at a specific day?" or "Should I check for conflicts?"
"""

TOOL_FUNCTIONS = {
    "get_calendar_events": get_calendar_events,
    "find_conflicts": find_conflicts,
    "suggest_optimizations": suggest_optimizations,
}


async def handle_tool_call(function_call):
    """Execute a tool call and return the result."""
    name = function_call.name
    args = dict(function_call.args) if function_call.args else {}

    func = TOOL_FUNCTIONS.get(name)
    if not func:
        return {"error": f"Unknown tool: {name}"}

    try:
        result = func(**args)
        return result
    except Exception as e:
        return {"error": f"Tool execution failed: {str(e)}"}


async def _process_session_response(session):
    """Process responses from the Live API session, handling tool calls."""
    async for message in session.receive():
        if message.tool_call:
            for fc in message.tool_call.function_calls:
                print(f"  🔧 Calling {fc.name}...")
                result = await handle_tool_call(fc)

                await session.send_tool_response(
                    function_responses=[
                        types.FunctionResponse(
                            name=fc.name,
                            response=result,
                        )
                    ]
                )
            continue

        if message.server_content:
            if message.server_content.model_turn:
                for part in message.server_content.model_turn.parts:
                    if part.text:
                        print(f"  📅 Analyst: {part.text}")
                    if part.inline_data:
                        print(f"  🔊 [Audio response: {len(part.inline_data.data)} bytes]")

            if message.server_content.turn_complete:
                break


async def run_voice_agent():
    """Run the voice agent with Gemini Live API for real-time audio interaction."""
    client = genai.Client()

    config = types.LiveConnectConfig(
        response_modalities=["AUDIO"],
        tools=[TOOL_DECLARATIONS],
        system_instruction=types.Content(
            parts=[types.Part(text=SYSTEM_INSTRUCTION)]
        ),
        speech_config=types.SpeechConfig(
            voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(
                    voice_name="Kore"
                )
            )
        ),
    )

    print("\n🎤 Voice Schedule Analyst — Gemini Live API")
    print("=" * 50)
    print("Connecting to Gemini Live API...")

    async with client.aio.live.connect(
        model="gemini-2.0-flash-live-001",
        config=config,
    ) as session:
        print("✅ Connected! Speak or type your schedule questions.")
        print("Type 'quit' to exit.\n")

        await session.send_client_content(
            turns=types.Content(
                role="user",
                parts=[types.Part(text="Hello! I'd like to know about my schedule.")],
            ),
            turn_complete=True,
        )

        await _process_session_response(session)

        while True:
            try:
                user_input = await asyncio.get_event_loop().run_in_executor(
                    None, lambda: input("\n🗣️  You: ")
                )
            except (EOFError, KeyboardInterrupt):
                print("\n👋 Goodbye!")
                break

            if user_input.lower().strip() in ("quit", "exit", "bye"):
                print("👋 Goodbye!")
                break

            if not user_input.strip():
                continue

            await session.send_client_content(
                turns=types.Content(
                    role="user",
                    parts=[types.Part(text=user_input)],
                ),
                turn_complete=True,
            )

            await _process_session_response(session)


async def run_text_agent():
    """Run the agent in text-only mode (for testing without audio hardware)."""
    client = genai.Client()

    config = types.LiveConnectConfig(
        response_modalities=["TEXT"],
        tools=[TOOL_DECLARATIONS],
        system_instruction=types.Content(
            parts=[types.Part(text=SYSTEM_INSTRUCTION)]
        ),
    )

    print("\n📅 Voice Schedule Analyst — Text Mode")
    print("=" * 50)
    print("Connecting to Gemini Live API...")

    async with client.aio.live.connect(
        model="gemini-2.0-flash-live-001",
        config=config,
    ) as session:
        print("✅ Connected! Type your schedule questions.")
        print("Type 'quit' to exit.\n")

        while True:
            try:
                user_input = await asyncio.get_event_loop().run_in_executor(
                    None, lambda: input("\n🗣️  You: ")
                )
            except (EOFError, KeyboardInterrupt):
                print("\n👋 Goodbye!")
                break

            if user_input.lower().strip() in ("quit", "exit", "bye"):
                print("👋 Goodbye!")
                break

            if not user_input.strip():
                continue

            await session.send_client_content(
                turns=types.Content(
                    role="user",
                    parts=[types.Part(text=user_input)],
                ),
                turn_complete=True,
            )

            await _process_session_response(session)


def main():
    """Entry point — run voice agent, fall back to text mode."""
    mode = sys.argv[1] if len(sys.argv) > 1 else "text"

    if mode == "voice":
        asyncio.run(run_voice_agent())
    else:
        asyncio.run(run_text_agent())


if __name__ == "__main__":
    main()
