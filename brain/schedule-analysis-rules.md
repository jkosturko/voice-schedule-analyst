# Schedule Analysis Rules — Voice Schedule Analyst

> Created: 2026-03-15
> Agent: schedule-analyst
> Framework: Google ADK + Gemini Live API

## Voice Output Rules
- Always speak in natural, conversational tone — not robotic lists
- Lead with the most important finding (conflicts first, then opportunities)
- Keep spoken responses under 30 seconds unless user asks for detail
- Use time references the user understands ("tomorrow morning" not "2026-03-17T09:00:00")
- When reporting conflicts, state both events and the overlap clearly

## Schedule Analysis Rules
- Rule 1: Creative blocks (Deep Work, Focus Time, Creative Block) are protected — never suggest removing them
- Rule 2: Flag triple-bookings as critical, double-bookings as warnings
- Rule 3: Travel events need buffer time — 1.5 hours + commute before departure
- Rule 4: Back-to-back meetings (>3 consecutive) should trigger a "meeting fatigue" warning
- Rule 5: Gaps shorter than 30 minutes between meetings aren't useful — flag as "dead time"
- Rule 6: Morning routines (before 9am) should be protected unless user explicitly asks
- Rule 7: Family events take priority over moveable work events

## Optimization Preferences
- Consolidate meetings into blocks when possible (meeting-free afternoons > scattered meetings)
- Protect peak energy windows (typically 10am-12pm) for deep work
- Suggest moving low-priority meetings to fill gaps rather than creating new blocks
- Weekend events are personal — don't optimize them for productivity
