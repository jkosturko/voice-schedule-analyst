"""Google Calendar tools for the Schedule Analyst agent.

These tools fetch real calendar data and return structured results
that the agent can reason about and speak back to the user.

Auth modes:
  - OAuth (local dev): Uses credentials.json + token.json via InstalledAppFlow
  - Service account (Cloud Run): Uses GOOGLE_SERVICE_ACCOUNT_JSON env var
"""

import os
import json
import logging
from datetime import datetime, timedelta
from typing import Optional

from google.oauth2.credentials import Credentials
from google.oauth2 import service_account
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]
TOKEN_PATH = os.environ.get("TOKEN_PATH", "token.json")


def _get_calendar_service():
    """Build and return an authenticated Google Calendar API service.

    Supports two auth modes:
      1. Service account (GOOGLE_SERVICE_ACCOUNT_JSON env var) — for Cloud Run
      2. OAuth (credentials.json + token.json) — for local development
    """
    # Mode 1: Service account (Cloud Run / production)
    sa_json = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
    if sa_json:
        info = json.loads(sa_json)
        creds = service_account.Credentials.from_service_account_info(info, scopes=SCOPES)
        target_user = os.environ.get("CALENDAR_OWNER_EMAIL")
        if target_user:
            creds = creds.with_subject(target_user)
        return build("calendar", "v3", credentials=creds)

    # Mode 2: OAuth (local development)
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
            if not os.path.exists(credentials_path):
                raise FileNotFoundError(
                    f"No credentials found. Set GOOGLE_SERVICE_ACCOUNT_JSON for Cloud Run, "
                    f"or place {credentials_path} for local OAuth."
                )
            flow = InstalledAppFlow.from_client_secrets_file(credentials_path, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(TOKEN_PATH, "w") as token:
            token.write(creds.to_json())

    return build("calendar", "v3", credentials=creds)


def _parse_time_range(time_range: str) -> tuple[str, str]:
    """Convert natural language time range to ISO datetime bounds."""
    now = datetime.now()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    ranges = {
        "today": (today_start, today_start + timedelta(days=1)),
        "tomorrow": (today_start + timedelta(days=1), today_start + timedelta(days=2)),
        "this week": (today_start, today_start + timedelta(days=(7 - now.weekday()))),
        "next week": (
            today_start + timedelta(days=(7 - now.weekday())),
            today_start + timedelta(days=(14 - now.weekday())),
        ),
        "next 3 days": (today_start, today_start + timedelta(days=3)),
        "next 7 days": (today_start, today_start + timedelta(days=7)),
    }

    start, end = ranges.get(time_range.lower().strip(), ranges["this week"])
    return start.isoformat() + "Z", end.isoformat() + "Z"


def _format_event(event: dict) -> dict:
    """Extract relevant fields from a Google Calendar event."""
    start = event.get("start", {})
    end = event.get("end", {})

    start_str = start.get("dateTime", start.get("date", ""))
    end_str = end.get("dateTime", end.get("date", ""))

    return {
        "id": event.get("id", ""),
        "summary": event.get("summary", "(No title)"),
        "start": start_str,
        "end": end_str,
        "location": event.get("location", ""),
        "description": event.get("description", "")[:200],
        "attendees": [
            a.get("email", "") for a in event.get("attendees", [])[:5]
        ],
        "status": event.get("status", "confirmed"),
        "is_all_day": "date" in start and "dateTime" not in start,
    }


def get_calendar_events(time_range: str = "this week") -> dict:
    """Fetch calendar events for the specified time range.

    Args:
        time_range: Natural language time range like 'today', 'this week',
                    'tomorrow', 'next 3 days', 'next 7 days'. Defaults to 'this week'.

    Returns:
        Dictionary with events list, count, and time range queried.
    """
    try:
        service = _get_calendar_service()
        time_min, time_max = _parse_time_range(time_range)

        events_result = (
            service.events()
            .list(
                calendarId="primary",
                timeMin=time_min,
                timeMax=time_max,
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
            "count": len(events),
            "time_range": time_range,
            "time_min": time_min,
            "time_max": time_max,
        }
    except FileNotFoundError:
        return {
            "error": "Calendar credentials not found. Please set up OAuth credentials.",
            "events": [],
            "count": 0,
        }
    except Exception as e:
        return {
            "error": f"Failed to fetch calendar events: {str(e)}",
            "events": [],
            "count": 0,
        }


def find_conflicts(time_range: str = "this week") -> dict:
    """Find scheduling conflicts (overlapping events) in the given time range.

    Args:
        time_range: Natural language time range. Defaults to 'this week'.

    Returns:
        Dictionary with conflicts found, their severity, and affected events.
    """
    result = get_calendar_events(time_range)
    if result.get("error"):
        return result

    events = result["events"]
    conflicts = []

    # Sort by start time and check overlaps
    timed_events = [e for e in events if not e["is_all_day"] and e["start"]]
    timed_events.sort(key=lambda e: e["start"])

    for i in range(len(timed_events)):
        for j in range(i + 1, len(timed_events)):
            e1 = timed_events[i]
            e2 = timed_events[j]

            e1_end = e1["end"]
            e2_start = e2["start"]

            if e1_end > e2_start:
                conflicts.append({
                    "event_1": e1["summary"],
                    "event_1_time": f"{e1['start']} - {e1['end']}",
                    "event_2": e2["summary"],
                    "event_2_time": f"{e2['start']} - {e2['end']}",
                    "severity": "critical" if _count_overlaps_at(timed_events, e2["start"]) >= 3 else "warning",
                })

    # Check for back-to-back meetings (>3 consecutive)
    back_to_back_chains = _find_back_to_back(timed_events)

    # Check for dead time (gaps < 30 min between meetings)
    dead_time = _find_dead_time(timed_events)

    return {
        "conflicts": conflicts,
        "conflict_count": len(conflicts),
        "back_to_back_warnings": back_to_back_chains,
        "dead_time_gaps": dead_time,
        "total_events_checked": len(timed_events),
        "time_range": time_range,
    }


def _count_overlaps_at(events: list, time_str: str) -> int:
    """Count how many events overlap at a given time."""
    count = 0
    for e in events:
        if e["start"] <= time_str < e["end"]:
            count += 1
    return count


def _find_back_to_back(events: list) -> list:
    """Find chains of 3+ back-to-back meetings (< 15 min gap)."""
    chains = []
    current_chain = [events[0]] if events else []

    for i in range(1, len(events)):
        prev_end = events[i - 1]["end"]
        curr_start = events[i]["start"]

        try:
            gap_minutes = (
                datetime.fromisoformat(curr_start.replace("Z", "+00:00"))
                - datetime.fromisoformat(prev_end.replace("Z", "+00:00"))
            ).total_seconds() / 60
        except (ValueError, TypeError):
            current_chain = [events[i]]
            continue

        if gap_minutes <= 15:
            current_chain.append(events[i])
        else:
            if len(current_chain) >= 3:
                chains.append({
                    "count": len(current_chain),
                    "events": [e["summary"] for e in current_chain],
                    "warning": f"Meeting fatigue alert: {len(current_chain)} consecutive meetings",
                })
            current_chain = [events[i]]

    if len(current_chain) >= 3:
        chains.append({
            "count": len(current_chain),
            "events": [e["summary"] for e in current_chain],
            "warning": f"Meeting fatigue alert: {len(current_chain)} consecutive meetings",
        })

    return chains


def _find_dead_time(events: list) -> list:
    """Find gaps between events that are too short to be useful (< 30 min)."""
    dead_gaps = []

    for i in range(1, len(events)):
        prev_end = events[i - 1]["end"]
        curr_start = events[i]["start"]

        try:
            gap_minutes = (
                datetime.fromisoformat(curr_start.replace("Z", "+00:00"))
                - datetime.fromisoformat(prev_end.replace("Z", "+00:00"))
            ).total_seconds() / 60
        except (ValueError, TypeError):
            continue

        if 0 < gap_minutes < 30:
            dead_gaps.append({
                "between": f"{events[i-1]['summary']} → {events[i]['summary']}",
                "gap_minutes": round(gap_minutes),
                "suggestion": "Too short for deep work. Consider merging adjacent meetings or extending a break.",
            })

    return dead_gaps
