"""Google Calendar tools for the Schedule Analyst agent.

Supports three auth modes (tried in order):
  1. Service account: set GOOGLE_SERVICE_ACCOUNT_JSON or GOOGLE_APPLICATION_CREDENTIALS
  2. OAuth token via env var (Cloud Run): set GOOGLE_CALENDAR_TOKEN_JSON to token.json contents
  3. OAuth token file (local dev): token.json on disk, or run `python -m schedule_analyst.auth`

Tools return structured dicts that the ADK agent reasons about via Gemini.
"""

import os
import json
from datetime import datetime, timedelta, timezone
from typing import Optional

from google.oauth2 import service_account
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from dateutil import parser as dateparser

SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]
TOKEN_PATH = os.path.join(os.path.dirname(__file__), "..", "token.json")

# Calendar ID — configurable via env var, defaults to "primary"
CALENDAR_ID = os.environ.get("GOOGLE_CALENDAR_ID", "primary")


def _get_calendar_service():
    """Build authenticated Google Calendar service.

    Tries service account first (Cloud Run), falls back to OAuth (local dev).
    """
    # Service account mode
    sa_json = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
    if sa_json:
        info = json.loads(sa_json)
        creds = service_account.Credentials.from_service_account_info(info, scopes=SCOPES)
        target_user = os.environ.get("CALENDAR_OWNER_EMAIL")
        if target_user:
            creds = creds.with_subject(target_user)
        return build("calendar", "v3", credentials=creds)

    sa_file = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if sa_file and os.path.exists(sa_file):
        creds = service_account.Credentials.from_service_account_file(sa_file, scopes=SCOPES)
        target_user = os.environ.get("CALENDAR_OWNER_EMAIL")
        if target_user:
            creds = creds.with_subject(target_user)
        return build("calendar", "v3", credentials=creds)

    # OAuth token via env var (Cloud Run — token.json contents as string)
    token_json = os.environ.get("GOOGLE_CALENDAR_TOKEN_JSON")
    if token_json:
        info = json.loads(token_json)
        creds = Credentials.from_authorized_user_info(info, SCOPES)
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        return build("calendar", "v3", credentials=creds)

    # OAuth token file (local development)
    creds = None
    if os.path.exists(TOKEN_PATH):
        creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            credentials_path = os.environ.get(
                "GOOGLE_CALENDAR_CREDENTIALS_PATH", "credentials.json"
            )
            flow = InstalledAppFlow.from_client_secrets_file(credentials_path, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(TOKEN_PATH, "w") as token:
            token.write(creds.to_json())

    return build("calendar", "v3", credentials=creds)


def _parse_time_range(time_range: str) -> tuple[datetime, datetime]:
    """Convert natural language time range to start/end datetimes."""
    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    tr = time_range.lower().strip()
    if tr in ("today", ""):
        return today_start, today_start + timedelta(days=1)
    elif tr == "tomorrow":
        return today_start + timedelta(days=1), today_start + timedelta(days=2)
    elif tr in ("this week", "week"):
        monday = today_start - timedelta(days=today_start.weekday())
        return monday, monday + timedelta(days=7)
    elif tr == "next week":
        monday = today_start - timedelta(days=today_start.weekday()) + timedelta(weeks=1)
        return monday, monday + timedelta(days=7)
    elif tr.startswith("next ") and tr.endswith(" days"):
        try:
            n = int(tr.replace("next ", "").replace(" days", ""))
            return today_start, today_start + timedelta(days=n)
        except ValueError:
            pass

    # Default: this week
    monday = today_start - timedelta(days=today_start.weekday())
    return monday, monday + timedelta(days=7)


def _format_event(event: dict) -> dict:
    """Extract relevant fields from a Google Calendar event."""
    start = event.get("start", {})
    end = event.get("end", {})
    return {
        "id": event.get("id", ""),
        "summary": event.get("summary", "(No title)"),
        "start": start.get("dateTime", start.get("date", "")),
        "end": end.get("dateTime", end.get("date", "")),
        "location": event.get("location", ""),
        "description": (event.get("description", "") or "")[:200],
        "attendees": [a.get("email", "") for a in event.get("attendees", [])[:5]],
        "status": event.get("status", "confirmed"),
    }


def _format_events_text(events: list[dict]) -> str:
    """Format events into a human-readable string for LLM context."""
    if not events:
        return "No events found in this time range."
    lines = []
    for ev in events:
        loc = f" at {ev['location']}" if ev.get("location") else ""
        lines.append(f"- {ev['summary']}: {ev['start']} to {ev['end']}{loc}")
    return "\n".join(lines)


def get_calendar_events(time_range: str = "this week") -> dict:
    """Fetch calendar events for the specified time range.

    Args:
        time_range: Natural language time range like 'today', 'this week',
                    'tomorrow', 'next 3 days'. Defaults to 'this week'.

    Returns:
        Dictionary with events list, count, and time range queried.
    """
    try:
        service = _get_calendar_service()
        start_dt, end_dt = _parse_time_range(time_range)

        events_result = (
            service.events()
            .list(
                calendarId=CALENDAR_ID,
                timeMin=start_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
                timeMax=end_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
                maxResults=50,
                singleEvents=True,
                orderBy="startTime",
            )
            .execute()
        )

        raw_events = events_result.get("items", [])
        events = [_format_event(e) for e in raw_events]

        return {
            "events": events,
            "events_text": _format_events_text(events),
            "count": len(events),
            "time_range": time_range,
        }
    except Exception as e:
        return {
            "error": f"Failed to fetch calendar events: {str(e)}",
            "events": [],
            "events_text": "Error fetching events.",
            "count": 0,
        }


def find_conflicts(time_range: str = "this week") -> dict:
    """Find scheduling conflicts, overlapping events, back-to-back chains, and dead time gaps.

    Args:
        time_range: Natural language time range. Defaults to 'this week'.

    Returns:
        Dictionary with conflicts, back-to-back warnings, dead time gaps, and counts.
    """
    result = get_calendar_events(time_range)
    if result.get("error"):
        return result

    events = result["events"]
    timed = []
    for ev in events:
        try:
            s = dateparser.isoparse(ev["start"])
            e = dateparser.isoparse(ev["end"])
            timed.append((s, e, ev))
        except (ValueError, TypeError):
            continue

    timed.sort(key=lambda x: x[0])

    # Detect overlaps
    conflicts = []
    for i in range(len(timed)):
        for j in range(i + 1, len(timed)):
            s1, e1, ev1 = timed[i]
            s2, e2, ev2 = timed[j]
            if s2 >= e1:
                break
            overlap_end = min(e1, e2)
            overlap_start = max(s1, s2)
            overlap_mins = int((overlap_end - overlap_start).total_seconds() / 60)
            if overlap_mins > 0:
                overlap_count = sum(1 for (si, ei, _) in timed if si <= s2 < ei)
                conflicts.append({
                    "event1": ev1["summary"],
                    "event2": ev2["summary"],
                    "overlap_minutes": overlap_mins,
                    "event1_time": ev1["start"],
                    "event2_time": ev2["start"],
                    "severity": "critical" if overlap_count >= 3 else "warning",
                })

    # Back-to-back chains (3+ meetings with <=5 min gap)
    back_to_back = []
    current_block = []
    for i, (s, e, ev) in enumerate(timed):
        if not current_block:
            current_block.append(ev)
            continue
        prev_end = timed[i - 1][1]
        gap = (s - prev_end).total_seconds() / 60
        if gap <= 5:
            current_block.append(ev)
        else:
            if len(current_block) >= 3:
                back_to_back.append({
                    "count": len(current_block),
                    "events": [e["summary"] for e in current_block],
                    "warning": f"{len(current_block)} back-to-back meetings — meeting fatigue risk",
                })
            current_block = [ev]
    if len(current_block) >= 3:
        back_to_back.append({
            "count": len(current_block),
            "events": [e["summary"] for e in current_block],
            "warning": f"{len(current_block)} back-to-back meetings — meeting fatigue risk",
        })

    # Dead time (gaps < 30 min)
    dead_time = []
    for i in range(len(timed) - 1):
        _, e1, ev1 = timed[i]
        s2, _, ev2 = timed[i + 1]
        gap_mins = int((s2 - e1).total_seconds() / 60)
        if 0 < gap_mins < 30:
            dead_time.append({
                "after_event": ev1["summary"],
                "before_event": ev2["summary"],
                "gap_minutes": gap_mins,
            })

    return {
        "conflicts": conflicts,
        "conflict_count": len(conflicts),
        "back_to_back_warnings": back_to_back,
        "dead_time_gaps": dead_time,
        "total_events_checked": len(timed),
        "time_range": time_range,
        "events_text": result["events_text"],
    }


# Protected event keywords — never suggest removing these
PROTECTED_KEYWORDS = frozenset([
    "deep work", "focus time", "creative block", "focus", "deep", "creative",
    "morning routine", "family", "kids", "pickup", "drop-off", "dropoff",
])

# Low-priority / moveable keywords — candidates for shifting
MOVEABLE_KEYWORDS = frozenset([
    "1:1", "sync", "standup", "stand-up", "check-in", "checkin",
    "optional", "office hours", "social", "lunch",
])


def _is_protected(summary: str) -> bool:
    """Check if an event is protected based on brain rules."""
    lower = summary.lower()
    return any(kw in lower for kw in PROTECTED_KEYWORDS)


def _is_moveable(summary: str) -> bool:
    """Check if an event is likely moveable."""
    lower = summary.lower()
    return any(kw in lower for kw in MOVEABLE_KEYWORDS)


def suggest_optimizations(focus: str = "general", time_range: str = "next 7 days") -> dict:
    """Suggest specific schedule optimizations based on calendar data and brain rules.

    Args:
        focus: What to optimize for — 'deep work', 'meeting consolidation',
               'travel prep', 'general'. Defaults to 'general'.
        time_range: Time range to analyze. Defaults to 'next 7 days'.

    Returns:
        Dictionary with optimization suggestions, moveable events, and protected events.
    """
    conflicts_result = find_conflicts(time_range=time_range)
    if conflicts_result.get("error"):
        return conflicts_result

    events_result = get_calendar_events(time_range=time_range)
    events = events_result.get("events", [])

    suggestions = []
    moveable_events = []
    protected_events = []

    # Classify events
    for ev in events:
        summary = ev.get("summary", "")
        if _is_protected(summary):
            protected_events.append(summary)
        elif _is_moveable(summary):
            moveable_events.append(summary)

    # Suggestion: resolve conflicts by moving low-priority events
    for conflict in conflicts_result.get("conflicts", []):
        ev1, ev2 = conflict["event1"], conflict["event2"]
        if _is_moveable(ev1) and not _is_moveable(ev2):
            suggestions.append({
                "action": "move",
                "event": ev1,
                "reason": f"Conflicts with {ev2} — {ev1} is lower priority and could shift",
            })
        elif _is_moveable(ev2) and not _is_moveable(ev1):
            suggestions.append({
                "action": "move",
                "event": ev2,
                "reason": f"Conflicts with {ev1} — {ev2} is lower priority and could shift",
            })
        else:
            suggestions.append({
                "action": "reschedule",
                "event": f"{ev1} or {ev2}",
                "reason": f"Both overlap by {conflict['overlap_minutes']} minutes — one needs to move",
            })

    # Suggestion: fill dead time by shifting nearby moveable events
    for gap in conflicts_result.get("dead_time_gaps", []):
        after = gap["after_event"]
        before = gap["before_event"]
        if _is_moveable(before):
            suggestions.append({
                "action": "shift",
                "event": before,
                "reason": f"{gap['gap_minutes']} min dead time after {after} — shift {before} earlier to consolidate",
            })

    # Suggestion: break up back-to-back blocks
    for b2b in conflicts_result.get("back_to_back_warnings", []):
        moveable_in_block = [e for e in b2b["events"] if _is_moveable(e)]
        if moveable_in_block:
            suggestions.append({
                "action": "reschedule",
                "event": moveable_in_block[0],
                "reason": f"Part of a {b2b['count']}-meeting back-to-back chain — move to create a break",
            })

    # Focus-specific suggestions
    focus_lower = focus.lower()
    if "deep work" in focus_lower:
        # Check if mornings (10am-12pm peak energy) are meeting-free
        timed = []
        for ev in events:
            try:
                s = dateparser.isoparse(ev["start"])
                timed.append((s, ev))
            except (ValueError, TypeError):
                continue
        morning_meetings = [
            ev["summary"] for s, ev in timed
            if 10 <= s.hour < 12 and not _is_protected(ev["summary"])
        ]
        if morning_meetings:
            suggestions.append({
                "action": "block",
                "event": "10am-12pm peak energy window",
                "reason": f"Morning has {len(morning_meetings)} meetings ({', '.join(morning_meetings[:3])}) — protect this window for deep work",
            })

    elif "meeting" in focus_lower or "consolidat" in focus_lower:
        suggestions.append({
            "action": "consolidate",
            "event": "scattered meetings",
            "reason": "Group all moveable meetings into afternoon blocks to free morning for focus",
        })

    return {
        "suggestions": suggestions,
        "suggestion_count": len(suggestions),
        "moveable_events": moveable_events,
        "protected_events": protected_events,
        "focus": focus,
        "events_text": events_result.get("events_text", ""),
        "total_events": len(events),
    }
