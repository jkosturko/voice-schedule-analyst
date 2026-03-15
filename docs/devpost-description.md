# Voice Schedule Analyst

## The Problem

Knowledge workers spend 5+ hours per week in meetings, yet most calendar tools are passive — they show events but don't analyze them. Double-bookings go unnoticed until it's too late. Back-to-back meeting marathons cause fatigue. Dead time gaps between meetings waste potential focus hours. And reviewing a packed calendar visually is slow and error-prone.

What if your calendar could talk to you — proactively surfacing conflicts, warning about meeting fatigue, and suggesting concrete optimizations?

## What It Does

Voice Schedule Analyst is a voice-first AI calendar assistant built on the Gemini Live API. Instead of reading through a crowded calendar UI, you simply ask: *"What does tomorrow look like?"* — and the agent speaks back a concise briefing.

**Core features:**

- **Conflict detection** — Identifies overlapping events, flags double-bookings as warnings and triple-bookings as critical
- **Meeting fatigue alerts** — Detects chains of 3+ back-to-back meetings and warns about burnout risk
- **Dead time analysis** — Finds gaps shorter than 30 minutes between meetings that are too short for meaningful work
- **Schedule optimization** — Suggests specific actions: move, shift, block, consolidate, or reschedule — with reasoning
- **Protected events** — Respects deep work blocks, family events, and morning routines — never suggests removing them
- **Natural voice interaction** — Responses are conversational and concise (~30 seconds), not robotic lists of data

## How It Works

The agent connects to your Google Calendar via the Calendar API and analyzes your real events. When you speak (or type), the Gemini Live API streams your audio in real-time. The agent reasons about your schedule using function calling — invoking calendar tools to fetch events, detect conflicts, and generate optimization suggestions. It then speaks back a natural-language briefing through the Kore voice.

A configurable "brain" (a Markdown rules file) defines analysis preferences: which events are protected, what constitutes meeting fatigue, how to prioritize conflicts, and when to suggest deep work blocks. This separation of rules from code makes the agent's behavior transparent and customizable.

## Architecture

- **Google ADK** — Agent framework with `root_agent` discovery, tool registration, and session management
- **Gemini Live API** — Real-time bidirectional audio streaming via `bidiGenerateContent` for voice interaction
- **DualModelGemini** — Custom `Gemini` subclass that routes text chat through `gemini-2.5-flash` (generateContent) and voice through `gemini-2.5-flash-native-audio-latest` (bidiGenerateContent), since no single model supports both
- **Google Calendar API** — OAuth 2.0 authenticated access to real calendar data
- **Flask HTTP server** — REST endpoints for programmatic access and health checks
- **Cloud Run** — Serverless deployment target

## Data Sources

- **Google Calendar** — Real events from the user's calendar (OAuth 2.0, read-only scope)
- **Brain rules** — Human-readable Markdown configuration for analysis preferences

## Key Learnings

1. **The dual-model problem** — No single Gemini model supports both `generateContent` (text/tools) and `bidiGenerateContent` (live audio). We solved this by subclassing ADK's `Gemini` class to swap models at the connection layer — text uses `gemini-2.5-flash`, voice uses `gemini-2.5-flash-native-audio-latest`.

2. **Voice-first UX requires different design** — Calendar analysis that works as text (bullet lists, tables) fails as voice. We constrained responses to ~30 seconds, prioritized findings by severity, and used conversational framing ("Your morning has a conflict between...") instead of data dumps.

3. **Separating rules from reasoning** — Externalizing schedule analysis rules into a Markdown "brain" file lets the AI reason about preferences without hardcoding them. Adding a new rule (e.g., "protect Friday afternoons") requires zero code changes.

4. **ADK native audio integration** — Google ADK's agent framework handles tool orchestration, but live audio requires careful model routing. The `connect()` override pattern we developed is a clean way to add voice capabilities to any ADK agent.

## What Makes It Different

Most calendar assistants are reactive text chatbots — you ask a question, they look it up. Voice Schedule Analyst is **proactive and voice-native**. It analyzes your schedule holistically (conflicts, fatigue patterns, dead time, optimization opportunities) and delivers a spoken briefing that respects your time. The brain rules system makes its reasoning transparent and customizable, and the dual-model architecture enables seamless switching between text and voice interaction within the same agent.
