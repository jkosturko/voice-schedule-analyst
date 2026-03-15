# Voice Schedule Analyst

> Built for the [Gemini Live Agent Challenge 2026](https://ai.google.dev/gemini-api/docs/live-agent-challenge)

A **voice-first calendar analyst** powered by Google ADK and the Gemini Live API. Talk to it about your schedule — it speaks back conflicts, recommendations, and actionable optimizations.

## What It Does

- **Analyze your schedule** — finds conflicts, dead-time gaps, and back-to-back meeting fatigue
- **Suggest optimizations** — recommends specific changes (move, shift, block, protect) based on configurable brain rules
- **Answer questions** — "Am I free Thursday afternoon?" "What's my busiest day this week?"

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    User (Voice / Text)                   │
└─────────────────────┬───────────────────────────────────┘
                      │ audio stream / text
                      ▼
┌─────────────────────────────────────────────────────────┐
│              Gemini Live API                             │
│         (gemini-2.0-flash-live-001)                     │
│         Real-time audio ↔ text, interrupts              │
└─────────────────────┬───────────────────────────────────┘
                      │ function calls
                      ▼
┌─────────────────────────────────────────────────────────┐
│           Google ADK Agent (Cloud Run)                   │
│                                                         │
│  ┌──────────────┐ ┌──────────────┐ ┌────────────────┐  │
│  │ get_calendar  │ │ find_        │ │ suggest_       │  │
│  │ _events()     │ │ conflicts()  │ │ optimizations()│  │
│  └──────┬───────┘ └──────┬───────┘ └───────┬────────┘  │
│         │                │                  │           │
│         ▼                ▼                  ▼           │
│  ┌──────────────────────────────────────────────────┐   │
│  │          Google Calendar API v3                   │   │
│  │     (OAuth local / Service Account cloud)         │   │
│  └──────────────────────────────────────────────────┘   │
│                                                         │
│  ┌──────────────────────────────────────────────────┐   │
│  │       Brain Rules (brain/*.md)                    │   │
│  │  Protected events, fatigue thresholds, priorities │   │
│  └──────────────────────────────────────────────────┘   │
│                                                         │
│  ┌──────────────────────────────────────────────────┐   │
│  │    Gemini 2.0 Flash (summary generation)          │   │
│  │    Natural language responses for HTTP endpoints   │   │
│  └──────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────┘
```

### Three Ways to Run

| Mode | Command | Use Case |
|------|---------|----------|
| **ADK Web UI** | `adk web schedule_analyst` | Interactive development + testing |
| **Live API (voice/text)** | `python -m schedule_analyst` | Real-time voice conversations |
| **HTTP Server** | `python main.py` | Cloud Run / webhook integration |

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

| Requirement | How to Get It |
|-------------|---------------|
| Python 3.12+ | `python --version` — [install](https://www.python.org/downloads/) if needed |
| Google Cloud project | [console.cloud.google.com](https://console.cloud.google.com) — create or select a project |
| `GOOGLE_API_KEY` | [aistudio.google.com/apikey](https://aistudio.google.com/apikey) — create a Gemini API key |
| Calendar API enabled | Cloud Console → APIs & Services → Enable "Google Calendar API" |
| OAuth credentials | Cloud Console → APIs & Services → Credentials → Create OAuth 2.0 Client ID → Download JSON as `credentials.json` |

### Local Development

```bash
# 1. Clone and set up
git clone https://github.com/jkosturko/voice-schedule-analyst.git
cd voice-schedule-analyst
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 2. Configure environment
cp .env.example .env
# Edit .env — set GOOGLE_API_KEY at minimum

# 3. Authorize Google Calendar (one-time — opens browser for OAuth consent)
python -m schedule_analyst.auth

# 4. Run the agent (pick one):
adk web schedule_analyst          # ADK web UI — best for development
python -m schedule_analyst        # Live API — voice/text mode
python main.py                    # HTTP server — for testing endpoints
```

### Deploy to Cloud Run

The deploy script handles everything: enables APIs, creates an Artifact Registry repo, builds via Cloud Build, and deploys to Cloud Run.

```bash
# Prerequisites: gcloud CLI installed + authenticated
gcloud auth login
gcloud config set project your-project-id

# Set your API key (passed to Cloud Run as env var)
export GOOGLE_API_KEY=your-gemini-api-key

# Deploy in one command
./scripts/deploy.sh your-project-id us-east1

# The script outputs the service URL. Verify:
curl https://your-service-url/health
```

**What the deploy script does (5 steps):**
1. Enables Cloud Run, Artifact Registry, Cloud Build, and Calendar APIs
2. Creates a Docker repository in Artifact Registry (idempotent — safe to re-run)
3. Builds the container image via Cloud Build
4. Deploys to Cloud Run (512MB RAM, 120s timeout, auto-scaling 0→3 instances)
5. Prints the service URL + example curl commands

### Local Docker Testing

```bash
# Build and run locally (no GCP needed)
./scripts/docker-build.sh

# Or build only (no run)
./scripts/docker-build.sh --build
```

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
├── schedule_analyst/           # ADK agent package
│   ├── __init__.py            # Exports root_agent for ADK discovery
│   ├── __main__.py            # Entry point for `python -m schedule_analyst`
│   ├── agent.py               # Root agent definition (ADK entry point)
│   ├── calendar_tools.py      # Google Calendar API tools (3 functions)
│   ├── live_agent.py          # Gemini Live API voice interface
│   └── auth.py                # OAuth helper for local setup
├── brain/
│   └── schedule-analysis-rules.md  # Configurable analysis preferences
├── tests/
│   └── test_calendar_tools.py # 36 tests — fully mocked, no creds needed
├── scripts/
│   ├── deploy.sh              # One-command Cloud Run deployment
│   └── docker-build.sh        # Local Docker build + run
├── main.py                    # Flask HTTP server for Cloud Run
├── Dockerfile                 # Production container (non-root, gunicorn)
├── .dockerignore              # Lean build context
├── .env.example               # Environment variable template
└── requirements.txt           # Python dependencies
```

## Testing

36 tests covering all core logic — no credentials needed (fully mocked):

```bash
source .venv/bin/activate
python -m pytest tests/ -v
```

Test coverage:
- Time range parsing (today, tomorrow, this week, next N days, fallbacks)
- Event formatting and field extraction
- Conflict detection (overlaps, severity classification)
- Back-to-back meeting chain detection
- Dead-time gap identification
- Event classification (protected vs moveable)
- Optimization suggestions (conflict resolution, deep work, consolidation)
- All Flask HTTP endpoints (health, analyze, optimize, question)
- Error propagation from Calendar API failures

## Competition Category

**Live Agents** — Real-time audio/vision with interrupt capability.

This agent demonstrates:
- **Natural voice interaction** — speaks conversationally, not robotic lists
- **Real data integration** — live Google Calendar events, not synthetic data
- **Configurable brain** — human-readable markdown rules loaded at startup, no code changes needed
- **Three tool functions** — calendar fetch, conflict detection, optimization suggestions
- **Production-ready deployment** — Dockerfile, Artifact Registry, Cloud Run with one-command deploy
- **Comprehensive test suite** — 36 tests, all mocked, runs in <1s

## License

MIT
