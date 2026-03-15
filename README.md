# Voice Schedule Analyst

> Built for the [Gemini Live Agent Challenge 2026](https://ai.google.dev/gemini-api/docs/live-agent-challenge)

A **voice-first calendar analyst** powered by Google ADK and the Gemini Live API. Talk to it about your schedule — it speaks back conflicts, recommendations, and actionable optimizations.

## What It Does

- **Analyze your schedule** — finds conflicts, dead-time gaps, and back-to-back meeting fatigue
- **Suggest optimizations** — recommends specific changes (move, shift, block, protect) based on configurable brain rules
- **Answer questions** — "Am I free Thursday afternoon?" "What's my busiest day this week?"

## Architecture

```
User (Voice) ──► Gemini Live API (audio in/out)
                      │
                      ▼
              Google ADK Agent
              (Cloud Run on GCP)
                      │
              ┌───────┼───────┐
              ▼       ▼       ▼
         Google    Gemini   Brain Rules
        Calendar   2.0     (configurable
          API    (reasoning)  preferences)
```

## Tech Stack

| Component | Technology |
|-----------|-----------|
| Agent Framework | [Google Agent Development Kit (ADK)](https://google.github.io/adk-docs/) |
| Voice Interface | Gemini Live API (`gemini-2.0-flash-live-001`) |
| LLM Reasoning | Gemini 2.0 Flash |
| Calendar Data | Google Calendar API v3 |
| Deployment | Google Cloud Run |
| Language | Python 3.12 |

## Quick Start

### Prerequisites

- Python 3.12+
- Google Cloud project with Calendar API enabled
- Google GenAI API key (`GOOGLE_API_KEY`)
- OAuth client credentials (`credentials.json`) for Calendar access

### Local Development

```bash
# Clone and set up
git clone https://github.com/jkosturko/voice-schedule-analyst.git
cd voice-schedule-analyst
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Configure
cp .env.example .env
# Edit .env with your API key

# Authorize Google Calendar (one-time — opens browser)
python -m schedule_analyst.auth

# Run with ADK web UI
adk web schedule_analyst

# Or run the Live API agent (text mode)
python -m schedule_analyst

# Or run the HTTP server
python main.py
```

### Deploy to Cloud Run

```bash
# Set your project
export GOOGLE_CLOUD_PROJECT=your-project-id

# Deploy (builds + deploys in one step)
./scripts/deploy.sh $GOOGLE_CLOUD_PROJECT us-east1
```

The deploy script enables required APIs, builds via Cloud Build, and deploys to Cloud Run.

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Health check |
| `/schedule-analyst/analyze` | POST | Analyze schedule for conflicts and gaps |
| `/schedule-analyst/optimize` | POST | Suggest schedule optimizations |
| `/schedule-analyst/question` | POST | Answer a schedule question |

### Examples

```bash
# Analyze this week's schedule
curl -X POST http://localhost:8080/schedule-analyst/analyze \
  -H "Content-Type: application/json" \
  -d '{"time_range": "this week"}'

# Ask a question
curl -X POST http://localhost:8080/schedule-analyst/question \
  -H "Content-Type: application/json" \
  -d '{"question": "Am I free Thursday afternoon?"}'

# Get optimization suggestions
curl -X POST http://localhost:8080/schedule-analyst/optimize \
  -H "Content-Type: application/json" \
  -d '{"focus": "deep work"}'
```

## Brain Rules

The agent's analysis preferences are configurable via [`brain/schedule-analysis-rules.md`](brain/schedule-analysis-rules.md):

- Creative blocks are **protected** — never suggests removing them
- Triple-bookings = critical, double-bookings = warning
- Travel events need 1.5hr buffer before departure
- 3+ consecutive meetings triggers fatigue warning
- Gaps under 30 min between meetings = "dead time"
- Family events take priority over moveable work events

Brain rules are loaded at agent startup and influence all analysis and recommendations. They're human-readable markdown — edit them to match your preferences.

## Voice Interaction

The agent uses the Gemini Live API for real-time voice conversations. It:

1. Listens to your voice input via streaming audio
2. Calls tools (calendar fetch, conflict detection) based on your question
3. Generates a natural, spoken response — not robotic lists, but conversational analysis
4. Supports natural interruptions (Live API feature)

Voice name: **Kore** — warm and professional.

## Project Structure

```
voice-schedule-analyst/
├── schedule_analyst/        # ADK agent package
│   ├── agent.py            # Root agent definition (ADK entry point)
│   ├── calendar_tools.py   # Google Calendar API tools
│   ├── live_agent.py       # Gemini Live API voice interface
│   └── auth.py             # OAuth helper for local setup
├── brain/                   # Configurable analysis rules
├── main.py                  # HTTP server for Cloud Run
├── Dockerfile               # Container config
├── scripts/deploy.sh        # Cloud Run deployment
└── requirements.txt
```

## Competition Category

**Live Agents** — Real-time audio/vision with interrupt capability.

This agent demonstrates:
- Natural voice interaction (not a text chatbot)
- Real Google Calendar data integration
- Configurable analysis rules (brain files)
- Clean Cloud Run deployment with automated deploy script

## License

MIT
