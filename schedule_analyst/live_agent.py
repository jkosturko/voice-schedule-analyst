"""Gemini Live API integration for real-time voice interaction.

This module provides the voice interface using Gemini's Live API
for real-time audio streaming. The user speaks, the agent listens,
queries the calendar, and speaks back analysis.

Supports three modes:
  - voice: Full duplex audio (mic → Live API → speakers)
  - text:  Text-only Live API session (for testing without audio hardware)
  - demo:  Scripted demo mode for recording competition video
"""

import asyncio
import base64
import json
import os
import sys
import wave
import io
import struct
import logging

from google import genai
from google.genai import types

from .calendar_tools import get_calendar_events, find_conflicts, suggest_optimizations

logger = logging.getLogger(__name__)

# Audio constants — Live API expects 16kHz mono 16-bit PCM
SEND_SAMPLE_RATE = 16000
RECEIVE_SAMPLE_RATE = 24000  # Live API outputs 24kHz
CHUNK_SIZE = 1024
FORMAT_BYTES = 2  # 16-bit = 2 bytes per sample
CHANNELS = 1

# Load brain rules for system instruction
BRAIN_PATH = os.path.join(os.path.dirname(__file__), "..", "brain", "schedule-analysis-rules.md")
try:
    with open(BRAIN_PATH, "r") as f:
        BRAIN_RULES = f.read()
except FileNotFoundError:
    BRAIN_RULES = ""

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

SYSTEM_INSTRUCTION = f"""You are a Voice Schedule Analyst — a conversational, voice-first calendar assistant.

You help users understand and optimize their schedules by analyzing their Google Calendar events. You speak naturally, like a trusted chief of staff briefing their executive.

Voice Output Rules:
- Speak naturally and conversationally — not robotic lists
- Lead with the most important finding (conflicts first, then opportunities)
- Keep responses concise — under 30 seconds unless asked for detail
- Use human time references: "tomorrow morning" not ISO timestamps
- When reporting conflicts, clearly state both events and the overlap
- Never output raw JSON — speak in sentences
- Be warm but efficient

{BRAIN_RULES}

Always end with an offer to dig deeper: "Want me to look at a specific day?" or "Should I check for conflicts?"
"""

TOOL_FUNCTIONS = {
    "get_calendar_events": get_calendar_events,
    "find_conflicts": find_conflicts,
    "suggest_optimizations": suggest_optimizations,
}


def _check_api_key():
    """Verify GOOGLE_API_KEY is set before attempting connection."""
    key = os.environ.get("GOOGLE_API_KEY", "")
    if not key:
        print("ERROR: GOOGLE_API_KEY environment variable not set.")
        print("Set it with: export GOOGLE_API_KEY=your-key")
        print("Get a key at: https://aistudio.google.com/app/apikey")
        sys.exit(1)
    return key


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
        logger.error("[TOOL_ERROR] %s: %s", name, e)
        return {"error": f"Tool execution failed: {str(e)}"}


async def _process_session_response(session, audio_queue=None):
    """Process responses from the Live API session, handling tool calls.

    Args:
        session: The Live API session.
        audio_queue: Optional asyncio.Queue for audio playback.
                     If None, audio data is logged but not played.
    """
    async for message in session.receive():
        # Handle tool calls
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

        # Handle server content (text or audio)
        if message.server_content:
            if message.server_content.model_turn:
                for part in message.server_content.model_turn.parts:
                    if part.text:
                        print(f"  📅 Analyst: {part.text}")
                    if part.inline_data and part.inline_data.data:
                        if audio_queue is not None:
                            await audio_queue.put(part.inline_data.data)
                        else:
                            print(f"  🔊 [Audio: {len(part.inline_data.data)} bytes]")

            if message.server_content.turn_complete:
                if audio_queue is not None:
                    await audio_queue.put(None)  # Signal end of turn
                break


async def _mic_audio_stream(session):
    """Capture microphone audio and stream to Live API session.

    Uses pyaudio for cross-platform mic capture. Streams 16kHz mono PCM.
    """
    try:
        import pyaudio
    except ImportError:
        print("ERROR: pyaudio not installed. Run: pip install pyaudio")
        print("On macOS: brew install portaudio && pip install pyaudio")
        return

    pa = pyaudio.PyAudio()

    stream = pa.open(
        format=pyaudio.paInt16,
        channels=CHANNELS,
        rate=SEND_SAMPLE_RATE,
        input=True,
        frames_per_buffer=CHUNK_SIZE,
    )

    print("🎙️  Microphone active — speak now!")

    try:
        while True:
            data = await asyncio.get_event_loop().run_in_executor(
                None, lambda: stream.read(CHUNK_SIZE, exception_on_overflow=False)
            )
            # Send raw PCM audio to Live API
            await session.send_realtime_input(
                audio=types.Blob(
                    data=data,
                    mime_type=f"audio/pcm;rate={SEND_SAMPLE_RATE}",
                )
            )
    except asyncio.CancelledError:
        pass
    finally:
        stream.stop_stream()
        stream.close()
        pa.terminate()


async def _play_audio(audio_queue):
    """Play audio chunks from the queue through speakers.

    Receives 24kHz PCM from Live API and plays via pyaudio.
    """
    try:
        import pyaudio
    except ImportError:
        # Drain queue silently if pyaudio unavailable
        while True:
            chunk = await audio_queue.get()
            if chunk is None:
                break
        return

    pa = pyaudio.PyAudio()
    stream = pa.open(
        format=pyaudio.paInt16,
        channels=CHANNELS,
        rate=RECEIVE_SAMPLE_RATE,
        output=True,
    )

    try:
        while True:
            chunk = await audio_queue.get()
            if chunk is None:
                break
            await asyncio.get_event_loop().run_in_executor(
                None, lambda c=chunk: stream.write(c)
            )
    except asyncio.CancelledError:
        pass
    finally:
        stream.stop_stream()
        stream.close()
        pa.terminate()


async def run_voice_agent():
    """Run the voice agent with real-time microphone → Live API → speakers."""
    _check_api_key()
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
                    voice_name="Kore"  # Warm, professional voice
                )
            )
        ),
    )

    print("\n🎤 Voice Schedule Analyst — Gemini Live API")
    print("=" * 50)
    print("Connecting to Gemini Live API...")

    try:
        async with client.aio.live.connect(
            model="gemini-2.0-flash-live-001",
            config=config,
        ) as session:
            print("✅ Connected!")
            print("Speak naturally — the agent will respond with voice.")
            print("Press Ctrl+C to exit.\n")

            audio_queue = asyncio.Queue()

            # Start mic capture in background
            mic_task = asyncio.create_task(_mic_audio_stream(session))

            try:
                while True:
                    # Process each response turn, playing audio
                    play_task = asyncio.create_task(_play_audio(audio_queue))
                    await _process_session_response(session, audio_queue=audio_queue)
                    await play_task
            except asyncio.CancelledError:
                pass
            finally:
                mic_task.cancel()
                try:
                    await mic_task
                except asyncio.CancelledError:
                    pass

    except Exception as e:
        logger.error("[LIVE_API_ERROR] %s", e)
        print(f"\n❌ Connection error: {e}")
        print("Check your GOOGLE_API_KEY and internet connection.")


async def run_text_agent():
    """Run the agent in text-only mode (for testing without audio hardware)."""
    _check_api_key()
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

    try:
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

    except Exception as e:
        logger.error("[LIVE_API_ERROR] %s", e)
        print(f"\n❌ Connection error: {e}")
        print("Check your GOOGLE_API_KEY and internet connection.")


async def run_demo_agent():
    """Scripted demo mode — sends pre-written queries for video recording.

    Perfect for recording the 4-minute competition demo video.
    Runs in text mode with TEXT responses so output is visible on screen.
    """
    _check_api_key()
    client = genai.Client()

    config = types.LiveConnectConfig(
        response_modalities=["TEXT"],
        tools=[TOOL_DECLARATIONS],
        system_instruction=types.Content(
            parts=[types.Part(text=SYSTEM_INSTRUCTION)]
        ),
    )

    DEMO_QUERIES = [
        "Hey, what does my week look like?",
        "Are there any scheduling conflicts I should worry about?",
        "How can I optimize my schedule for more deep work time?",
        "Am I free Thursday afternoon?",
    ]

    print("\n🎬 Voice Schedule Analyst — Demo Mode")
    print("=" * 50)
    print("Connecting to Gemini Live API...")

    try:
        async with client.aio.live.connect(
            model="gemini-2.0-flash-live-001",
            config=config,
        ) as session:
            print("✅ Connected! Running demo sequence...\n")

            for i, query in enumerate(DEMO_QUERIES, 1):
                print(f"\n{'─' * 40}")
                print(f"  Demo Query {i}/{len(DEMO_QUERIES)}")
                print(f"  🗣️  User: {query}")
                print(f"{'─' * 40}")

                await session.send_client_content(
                    turns=types.Content(
                        role="user",
                        parts=[types.Part(text=query)],
                    ),
                    turn_complete=True,
                )

                await _process_session_response(session)

                # Pause between queries for readability in video
                if i < len(DEMO_QUERIES):
                    print("\n  ⏳ Next query in 3 seconds...")
                    await asyncio.sleep(3)

            print(f"\n{'=' * 50}")
            print("🎬 Demo complete!")

    except Exception as e:
        logger.error("[DEMO_ERROR] %s", e)
        print(f"\n❌ Error: {e}")


def main():
    """Entry point — select mode via CLI argument."""
    mode = sys.argv[1] if len(sys.argv) > 1 else "text"

    modes = {
        "voice": run_voice_agent,
        "text": run_text_agent,
        "demo": run_demo_agent,
    }

    runner = modes.get(mode)
    if not runner:
        print(f"Unknown mode: {mode}")
        print(f"Available modes: {', '.join(modes.keys())}")
        sys.exit(1)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    asyncio.run(runner())


if __name__ == "__main__":
    main()
