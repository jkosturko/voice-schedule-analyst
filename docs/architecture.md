# Architecture — Voice Schedule Analyst

## System Architecture

```mermaid
graph TB
    subgraph User["👤 User"]
        Mic["🎙️ Microphone<br/>16kHz mono PCM"]
        Speaker["🔊 Speakers<br/>24kHz mono PCM"]
    end

    subgraph GeminiLive["☁️ Gemini Live API"]
        LiveModel["gemini-2.0-flash-live-001<br/>Real-time streaming<br/>Natural interruptions"]
    end

    subgraph ADKAgent["🤖 Google ADK Agent — Cloud Run"]
        Router["ADK Root Agent<br/>schedule_analyst"]

        subgraph Tools["Calendar Tools"]
            T1["get_calendar_events()<br/>Fetch events by time range"]
            T2["find_conflicts()<br/>Overlaps, back-to-back,<br/>dead time detection"]
            T3["suggest_optimizations()<br/>Move, shift, block,<br/>protect, consolidate"]
        end

        subgraph Brain["🧠 Brain Rules"]
            BR["brain/schedule-analysis-rules.md<br/>• Protected events (deep work, family)<br/>• Fatigue thresholds (3+ meetings)<br/>• Priority rules (family > work)<br/>• Energy windows (10am-12pm)"]
        end

        subgraph HTTP["HTTP Server (Flask)"]
            Health["/health"]
            Analyze["/schedule-analyst/analyze"]
            Optimize["/schedule-analyst/optimize"]
            Question["/schedule-analyst/question"]
        end
    end

    subgraph GoogleAPIs["☁️ Google Cloud APIs"]
        CalAPI["Google Calendar API v3<br/>OAuth (local) / Service Account (cloud)"]
        GenAI["Gemini API<br/>Summary generation"]
    end

    subgraph Athena["👁️ Athena Observer (Optional)"]
        Dispatch["Dispatcher<br/>Webhook POST"]
        Score["Intent Scoring<br/>Langfuse traces"]
        SLO["SLO Dashboard<br/>Agent health"]
    end

    %% Voice flow
    Mic -->|"audio stream"| LiveModel
    LiveModel -->|"audio response"| Speaker
    LiveModel -->|"function_call"| Router
    Router -->|"function_response"| LiveModel

    %% Tool execution
    Router --> T1
    Router --> T2
    Router --> T3
    T1 --> CalAPI
    T2 --> CalAPI
    T3 --> CalAPI
    Brain -.->|"loaded at startup"| Router

    %% HTTP flow (Athena integration)
    Dispatch -->|"POST /analyze"| Analyze
    Analyze --> CalAPI
    Analyze --> GenAI
    Score -.->|"traces"| Dispatch

    %% Styling
    classDef google fill:#4285F4,stroke:#333,color:white
    classDef agent fill:#34A853,stroke:#333,color:white
    classDef user fill:#EA4335,stroke:#333,color:white
    classDef athena fill:#FBBC04,stroke:#333,color:black

    class LiveModel,CalAPI,GenAI google
    class Router,T1,T2,T3 agent
    class Mic,Speaker user
    class Dispatch,Score,SLO athena
```

## Data Flow

### Voice Mode (Competition Demo)

```mermaid
sequenceDiagram
    participant U as User (Voice)
    participant L as Gemini Live API
    participant A as ADK Agent
    participant C as Google Calendar
    participant B as Brain Rules

    U->>L: "What does my week look like?"
    Note over L: Audio → text transcription
    L->>A: function_call: get_calendar_events("this week")
    A->>C: Calendar API: list events
    C-->>A: 12 events
    A->>A: Format events for LLM
    A-->>L: function_response: {events, count: 12}
    Note over L: Generate spoken response<br/>using brain rules context
    L->>A: function_call: find_conflicts("this week")
    A->>C: Calendar API: list events
    C-->>A: events
    A->>A: Detect overlaps, B2B, dead time
    A-->>L: function_response: {conflicts: 2, b2b: 1}
    L-->>U: 🔊 "Your week is pretty packed with 12 events.<br/>I found two conflicts — Tuesday has overlapping<br/>meetings at 2pm. Want me to suggest fixes?"
```

### HTTP Mode (Athena Integration)

```mermaid
sequenceDiagram
    participant AT as Athena Dispatcher
    participant S as Flask Server
    participant C as Calendar API
    participant G as Gemini API
    participant L as Langfuse

    AT->>S: POST /schedule-analyst/analyze
    Note over AT: Intent scoring begins
    S->>C: Fetch events + conflicts
    C-->>S: Calendar data
    S->>G: Generate natural language summary
    G-->>S: Spoken summary text
    S-->>AT: {conflicts, summary, event_count}
    AT->>L: Log trace + intent score
```

## Component Responsibilities

| Component | Role | Technology |
|-----------|------|-----------|
| **Gemini Live API** | Real-time voice ↔ text, streaming, interruptions | `gemini-2.0-flash-live-001` |
| **ADK Root Agent** | Tool orchestration, system instruction, brain rules | `google-adk` |
| **Calendar Tools** | Event fetching, conflict detection, optimization logic | `google-api-python-client` |
| **Brain Rules** | Configurable analysis preferences (markdown) | Human-editable `.md` |
| **Flask Server** | HTTP endpoints for Cloud Run + Athena webhooks | `flask` + `gunicorn` |
| **Athena Observer** | Intent scoring, SLO tracking, Langfuse traces | External (optional) |

## Deployment

```mermaid
graph LR
    subgraph Local["💻 Local Development"]
        ADK["adk web / adk run"]
        Live["python -m schedule_analyst"]
        Flask["python main.py"]
    end

    subgraph GCP["☁️ Google Cloud Platform"]
        CB["Cloud Build"]
        AR["Artifact Registry"]
        CR["Cloud Run"]
    end

    Local -->|"scripts/deploy.sh"| CB
    CB --> AR
    AR --> CR
    CR -->|"PORT=8080"| Flask
```
