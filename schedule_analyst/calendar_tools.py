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

SCOPES = ["https://www.googleapis.com/auth/calendar"]
TOKEN_PATH = os.path.join(os.path.dirname(__file__), "..", "token.json")

# Calendar ID — configurable via env var, defaults to hackathon demo calendar
# NEVER default to "primary" — risks exposing personal calendar on public URLs
HACKATHON_CALENDAR = "556107517e83bcf5c9a7273f25bff29b2a6aff526d8ad1c5680a862f5831bf4a@group.calendar.google.com"
CALENDAR_ID = os.environ.get("GOOGLE_CALENDAR_ID", HACKATHON_CALENDAR)


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

    # Try parsing as a specific date (e.g., "Monday, March 16, 2026")
    try:
        parsed = dateparser.parse(time_range)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        day_start = parsed.replace(hour=0, minute=0, second=0, microsecond=0)
        return day_start, day_start + timedelta(days=1)
    except (ValueError, TypeError):
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
        "colorId": event.get("colorId", ""),
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
            # Normalize: make all datetimes timezone-aware (UTC) for comparison
            if s.tzinfo is None:
                s = s.replace(tzinfo=timezone.utc)
            if e.tzinfo is None:
                e = e.replace(tzinfo=timezone.utc)
            timed.append((s, e, ev))
        except (ValueError, TypeError):
            continue

    timed.sort(key=lambda x: x[0])

    # Detect overlaps — with rule-based proposals for each conflict
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
                conflict = {
                    "event1": ev1["summary"],
                    "event2": ev2["summary"],
                    "event1_id": ev1.get("id", ""),
                    "event2_id": ev2.get("id", ""),
                    "overlap_minutes": overlap_mins,
                    "event1_time": ev1["start"],
                    "event2_time": ev2["start"],
                    "event1_end": ev1["end"],
                    "event2_end": ev2["end"],
                    "severity": "critical" if overlap_count >= 3 else "warning",
                }

                # Generate rule-based proposal
                proposal = _build_conflict_proposal(
                    ev1, ev2, s1, e1, s2, e2, timed
                )
                conflict.update(proposal)
                conflicts.append(conflict)

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
            if len(current_block) >= 5:
                back_to_back.append({
                    "count": len(current_block),
                    "events": [e["summary"] for e in current_block],
                    "warning": f"{len(current_block)} back-to-back meetings — meeting fatigue risk",
                })
            current_block = [ev]
    if len(current_block) >= 5:
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


# Family/kids events — highest protection (R-02)
FAMILY_KEYWORDS = frozenset([
    "family", "kids", "pickup", "drop-off", "dropoff", "gymnastics",
    "school", "daycare", "pediatr", "recital", "soccer", "ballet",
])

# Deep work / focus — second-highest protection (R-01)
FOCUS_KEYWORDS = frozenset([
    "deep work", "focus time", "creative block", "focus", "deep", "creative",
    "morning routine",
])

# Travel events — third priority (R-07)
TRAVEL_KEYWORDS = frozenset([
    "flight", "airport", "travel", "transit", "drive to", "uber", "lyft",
    "train", "bus", "commute",
])

# Low-priority / moveable keywords — candidates for shifting (R-03)
MOVEABLE_KEYWORDS = frozenset([
    "1:1", "sync", "standup", "stand-up", "check-in", "checkin",
    "optional", "office hours", "social", "lunch",
])


def _find_next_free_slot(after_dt: datetime, duration: timedelta, timed: list, same_day: bool = True) -> Optional[datetime]:
    """Find the next free slot after a given time that fits the duration.

    Simple approach: try hourly slots from after_dt until end of day (or next day).
    """
    # Start searching from the next hour boundary after the conflict
    candidate = after_dt.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    end_of_search = candidate.replace(hour=18, minute=0)  # Don't schedule past 6 PM
    if same_day and candidate >= end_of_search:
        # Try next business day
        candidate = (candidate + timedelta(days=1)).replace(hour=9, minute=0)
        end_of_search = candidate.replace(hour=18, minute=0)

    while candidate + duration <= end_of_search:
        slot_end = candidate + duration
        # Check if this slot overlaps with any existing event
        conflict_found = False
        for s, e, _ in timed:
            if s < slot_end and e > candidate:
                conflict_found = True
                # Jump past this event
                candidate = e.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
                break
        if not conflict_found:
            return candidate
    return None


def _build_conflict_proposal(ev1: dict, ev2: dict, s1, e1, s2, e2, timed: list) -> dict:
    """Build a rule-based proposal for resolving a conflict.

    Priority table (who stays, who moves):
      1. R-02: Family/kids events stay
      2. R-01: Deep work/focus blocks stay
      3. R-07: Travel events stay
      4. Interviews (colorId=11) stay
      5. R-03: Moveable events (1:1, sync, standup) get moved
      6. Tiebreaker: shorter event moves

    Returns dict with: proposal, description, action_type, action_params, rule_ref
    """
    name1, name2 = ev1["summary"], ev2["summary"]

    # Score each event: higher = more protected (stays)
    score1 = _protection_score(ev1)
    score2 = _protection_score(ev2)

    # Both equally protected → needs_input
    if score1 == score2 and score1 >= 3:
        return {
            "proposal": {
                "action": "needs_input",
                "target_event": name1,
                "target_event_id": ev1.get("id", ""),
                "keep_event": name2,
                "keep_event_id": ev2.get("id", ""),
                "suggested_time": None,
                "reason": "Both events are important — choose which to move",
                "rule_ref": "R-00",
            },
            "description": f"Both '{name1}' and '{name2}' are important — which would you prefer to move?",
            "action_type": "needs_input",
            "action_params": None,
            "rule_ref": "R-00",
        }

    # Determine which to move (lower score moves)
    if score1 >= score2:
        keep_ev, move_ev = ev1, ev2
        keep_s, move_s, move_e = s1, s2, e2
        rule_ref = _rule_ref_for_score(score1)
        reason = _reason_for_score(score1, ev1["summary"])
    else:
        keep_ev, move_ev = ev2, ev1
        keep_s, move_s, move_e = s2, s1, e1
        rule_ref = _rule_ref_for_score(score2)
        reason = _reason_for_score(score2, ev2["summary"])

    # Find a free slot for the displaced event
    duration = move_e - move_s
    later_end = max(e1, e2)
    new_start = _find_next_free_slot(later_end, duration, timed)

    if new_start:
        new_start_iso = new_start.isoformat()
        time_str = new_start.strftime("%-I:%M %p")
        return {
            "proposal": {
                "action": "move",
                "target_event": move_ev["summary"],
                "target_event_id": move_ev.get("id", ""),
                "keep_event": keep_ev["summary"],
                "keep_event_id": keep_ev.get("id", ""),
                "suggested_time": new_start_iso,
                "reason": reason,
                "rule_ref": rule_ref,
            },
            "description": f"Move '{move_ev['summary']}' to {time_str} — '{keep_ev['summary']}' is {reason} ({rule_ref})",
            "action_type": "move_event",
            "action_params": {
                "event_id": move_ev.get("id", ""),
                "start_time": new_start_iso,
            },
            "rule_ref": rule_ref,
        }
    else:
        return {
            "proposal": {
                "action": "move",
                "target_event": move_ev["summary"],
                "target_event_id": move_ev.get("id", ""),
                "keep_event": keep_ev["summary"],
                "keep_event_id": keep_ev.get("id", ""),
                "suggested_time": None,
                "reason": reason,
                "rule_ref": rule_ref,
            },
            "description": f"Reschedule '{move_ev['summary']}' — no same-day slot available",
            "action_type": "reschedule",
            "action_params": {
                "event_id": move_ev.get("id", ""),
            },
            "rule_ref": rule_ref,
        }


def _protection_score(ev: dict) -> int:
    """Score how protected an event is. Higher = more protected (stays).

    5 = Family/kids (R-02)
    4 = Deep work/focus (R-01)
    3 = Travel (R-07)
    2 = Interview (colorId=11 or name contains 'interview')
    1 = Not moveable (default)
    0 = Moveable (1:1, sync, standup)
    """
    name = ev.get("summary", "").lower()
    if any(kw in name for kw in FAMILY_KEYWORDS):
        return 5
    if any(kw in name for kw in FOCUS_KEYWORDS):
        return 4
    if any(kw in name for kw in TRAVEL_KEYWORDS):
        return 3
    if ev.get("colorId") == "11" or "interview" in name:
        return 2
    if any(kw in name for kw in MOVEABLE_KEYWORDS):
        return 0
    return 1


def _rule_ref_for_score(score: int) -> str:
    """Map protection score to brain rule reference."""
    return {5: "R-02", 4: "R-01", 3: "R-07", 2: "R-01"}.get(score, "R-03")


def _reason_for_score(score: int, name: str) -> str:
    """Human-readable reason for why an event is protected."""
    return {
        5: "family/kids — protected",
        4: "deep work — protected",
        3: "travel — time-sensitive",
        2: "interview — high-priority",
    }.get(score, "higher priority")


def _is_protected(summary: str) -> bool:
    """Check if an event is protected based on brain rules."""
    lower = summary.lower()
    return (any(kw in lower for kw in FAMILY_KEYWORDS) or
            any(kw in lower for kw in FOCUS_KEYWORDS) or
            any(kw in lower for kw in TRAVEL_KEYWORDS))


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


# ═══════════════════════════════════════════════════════════════
# WRITE TOOLS — Calendar mutations (require calendar scope)
# ═══════════════════════════════════════════════════════════════


def update_event(event_id: str, summary: str = "", start_time: str = "", end_time: str = "") -> dict:
    """Update an existing calendar event — move it, rename it, or both.

    When moving an event (new start_time without end_time), the original
    duration is automatically preserved. No need to specify end_time.

    Args:
        event_id: The Google Calendar event ID to update.
        summary: New title for the event. Leave empty to keep current title.
        start_time: New start time in ISO 8601 format (e.g., '2026-03-16T14:00:00-04:00').
                    Leave empty to keep current start time.
        end_time: New end time in ISO 8601 format. Leave empty to auto-preserve
                  the original duration when start_time is provided.

    Returns:
        Dictionary with updated event details or error message.
    """
    try:
        service = _get_calendar_service()

        # Fetch current event first
        event = service.events().get(calendarId=CALENDAR_ID, eventId=event_id).execute()

        # Apply changes
        if summary:
            event["summary"] = summary

        if start_time and not end_time:
            # Auto-preserve duration: calculate original duration, apply to new start
            orig_start = event["start"].get("dateTime", event["start"].get("date", ""))
            orig_end = event["end"].get("dateTime", event["end"].get("date", ""))
            try:
                orig_s = dateparser.isoparse(orig_start)
                orig_e = dateparser.isoparse(orig_end)
                duration = orig_e - orig_s
                new_s = dateparser.isoparse(start_time)
                new_e = new_s + duration
                event["start"] = {"dateTime": start_time}
                event["end"] = {"dateTime": new_e.isoformat()}
            except (ValueError, TypeError):
                # Fallback: just set start, keep original end
                event["start"] = {"dateTime": start_time}
        elif start_time:
            event["start"] = {"dateTime": start_time}
            event["end"] = {"dateTime": end_time}
        elif end_time:
            event["end"] = {"dateTime": end_time}

        updated = service.events().update(
            calendarId=CALENDAR_ID, eventId=event_id, body=event
        ).execute()

        return {
            "success": True,
            "action": "updated",
            "event_id": updated["id"],
            "summary": updated.get("summary", ""),
            "start": updated["start"].get("dateTime", updated["start"].get("date", "")),
            "end": updated["end"].get("dateTime", updated["end"].get("date", "")),
            "link": updated.get("htmlLink", ""),
        }
    except Exception as e:
        return {"success": False, "error": f"Failed to update event: {str(e)}"}


def delete_event(event_id: str) -> dict:
    """Delete a calendar event by its ID. Use this for removing duplicates or cancelled meetings.

    Args:
        event_id: The Google Calendar event ID to delete.

    Returns:
        Dictionary confirming deletion or error message.
    """
    try:
        service = _get_calendar_service()

        # Fetch event details before deleting (for confirmation)
        event = service.events().get(calendarId=CALENDAR_ID, eventId=event_id).execute()
        event_summary = event.get("summary", "(No title)")

        service.events().delete(calendarId=CALENDAR_ID, eventId=event_id).execute()

        return {
            "success": True,
            "action": "deleted",
            "event_id": event_id,
            "deleted_summary": event_summary,
        }
    except Exception as e:
        return {"success": False, "error": f"Failed to delete event: {str(e)}"}


def create_event(summary: str, start_time: str, end_time: str, description: str = "") -> dict:
    """Create a new calendar event. Use this for adding focus blocks, packing time, transit blocks, etc.

    Args:
        summary: Title of the new event (e.g., 'Deep Work Block', 'Travel to Airport').
        start_time: Start time in ISO 8601 format (e.g., '2026-03-19T19:00:00-04:00').
        end_time: End time in ISO 8601 format (e.g., '2026-03-19T20:00:00-04:00').
        description: Optional description for the event.

    Returns:
        Dictionary with created event details or error message.
    """
    try:
        service = _get_calendar_service()

        event_body = {
            "summary": summary,
            "start": {"dateTime": start_time},
            "end": {"dateTime": end_time},
        }
        if description:
            event_body["description"] = description

        created = service.events().insert(calendarId=CALENDAR_ID, body=event_body).execute()

        return {
            "success": True,
            "action": "created",
            "event_id": created["id"],
            "summary": created.get("summary", ""),
            "start": created["start"].get("dateTime", created["start"].get("date", "")),
            "end": created["end"].get("dateTime", created["end"].get("date", "")),
            "link": created.get("htmlLink", ""),
        }
    except Exception as e:
        return {"success": False, "error": f"Failed to create event: {str(e)}"}
