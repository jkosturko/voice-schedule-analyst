# Schedule Analyst — Assertion Test Plan

**Source:** `agents/schedule-analyst/agent-manifest.yaml` (16 assertions across 3 actions)
**Environment:** Cloud Run (`https://schedule-analyst-994869332627.us-east1.run.app/`)
**Auth:** Basic Auth — username: any, password: APP_PASSWORD_HACKATHON

Every assertion below MUST PASS on the Cloud Run deployment before submission.
Local-only passes do NOT count.

---

## Action 1: analyze_schedule (6 assertions)

**Endpoint:** `POST /schedule-analyst/analyze`
**Payload:** `{"time_range": "this week"}`

| # | Assertion | Type | Check |
|---|-----------|------|-------|
| A1 | min_length(100) | output_summary ≥ 100 chars | Count chars in `summary` field. FAIL if < 100. |
| A2 | contains(schedule concepts) | summary contains at least ONE of: "conflict", "recommend", "schedule", "event", "calendar" | Case-insensitive search. FAIL if none found. |
| A3 | no_raw_json | summary has no `{` or `[` JSON fragments | Regex check for `\{.*:.*\}` or `\[.*\]` patterns. FAIL if found. |
| A4 | no_raw_templates | no `{{`, `{%`, `${`, `__PLACEHOLDER__` | FAIL if any template syntax found. |
| A5 | temporal grounding | summary contains at least ONE of: "AM", "PM", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday", "tomorrow", "today" | FAIL if no time/day references — means output is generic, not grounded in real calendar. |
| A6 | temporal_valid | any dates/times mentioned are real and in range | Manual check: do the days/times match actual calendar events? |

**curl test:**
```bash
curl -s -u user:PASSWORD \
  -X POST https://schedule-analyst-994869332627.us-east1.run.app/schedule-analyst/analyze \
  -H "Content-Type: application/json" \
  -d '{"time_range": "this week"}' | python3 -c "
import sys, json, re
r = json.load(sys.stdin)
s = r.get('summary', '')
print(f'Length: {len(s)} chars')
print(f'A1 min_length(100): {\"PASS\" if len(s) >= 100 else \"FAIL\"} ({len(s)})')
concepts = ['conflict', 'recommend', 'schedule', 'event', 'calendar']
found = [c for c in concepts if c.lower() in s.lower()]
print(f'A2 contains(concepts): {\"PASS\" if found else \"FAIL\"} (found: {found})')
print(f'A3 no_raw_json: {\"FAIL\" if re.search(r\"[{\\[][^}\\]]*[}\\]]\", s) else \"PASS\"}')
templates = ['{{', '{%', '\${', '__']
print(f'A4 no_raw_templates: {\"FAIL\" if any(t in s for t in templates) else \"PASS\"}')
days = ['AM', 'PM', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday', 'tomorrow', 'today']
found_days = [d for d in days if d.lower() in s.lower()]
print(f'A5 temporal_grounding: {\"PASS\" if found_days else \"FAIL\"} (found: {found_days})')
print(f'A6 temporal_valid: MANUAL CHECK — read the output')
print(f'\\nFull summary:\\n{s[:500]}')
"
```

---

## Action 2: suggest_optimization (5 assertions)

**Endpoint:** `POST /schedule-analyst/optimize`
**Payload:** `{"focus": "general"}`

| # | Assertion | Type | Check |
|---|-----------|------|-------|
| B1 | min_length(80) | suggestions ≥ 80 chars | Count chars in `suggestions` field. FAIL if < 80. |
| B2 | no_raw_json | no JSON fragments | Same as A3. |
| B3 | no_raw_templates | no template syntax | Same as A4. |
| B4 | contains(action verbs) | at least ONE of: "move", "shift", "block", "protect", "cancel", "reschedule", "add" | FAIL if no actionable verbs. |
| B5 | temporal grounding | at least ONE of: "AM", "PM", "Monday"–"Sunday" | FAIL if no specific time references. |

**curl test:**
```bash
curl -s -u user:PASSWORD \
  -X POST https://schedule-analyst-994869332627.us-east1.run.app/schedule-analyst/optimize \
  -H "Content-Type: application/json" \
  -d '{"focus": "general"}' | python3 -c "
import sys, json, re
r = json.load(sys.stdin)
s = r.get('suggestions', '')
print(f'Length: {len(s)} chars')
print(f'B1 min_length(80): {\"PASS\" if len(s) >= 80 else \"FAIL\"} ({len(s)})')
print(f'B2 no_raw_json: {\"FAIL\" if re.search(r\"[{\\[][^}\\]]*[}\\]]\", s) else \"PASS\"}')
templates = ['{{', '{%', '\${', '__']
print(f'B3 no_raw_templates: {\"FAIL\" if any(t in s for t in templates) else \"PASS\"}')
verbs = ['move', 'shift', 'block', 'protect', 'cancel', 'reschedule', 'add']
found = [v for v in verbs if v.lower() in s.lower()]
print(f'B4 contains(verbs): {\"PASS\" if found else \"FAIL\"} (found: {found})')
days = ['AM', 'PM', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
found_days = [d for d in days if d.lower() in s.lower()]
print(f'B5 temporal_grounding: {\"PASS\" if found_days else \"FAIL\"} (found: {found_days})')
print(f'\\nFull suggestions:\\n{s[:500]}')
"
```

---

## Action 3: answer_question (4 assertions)

**Endpoint:** `POST /schedule-analyst/question`
**Payload:** `{"question": "What does my week look like?"}`

| # | Assertion | Type | Check |
|---|-----------|------|-------|
| C1 | min_length(30) | answer ≥ 30 chars | FAIL if < 30. |
| C2 | no_raw_json | no JSON fragments | Same as A3. |
| C3 | no_raw_templates | no template syntax | Same as A4. |
| C4 | contains(calendar concepts) | at least ONE of: "AM", "PM", "Monday"–"Sunday", "event", "meeting", "block" | FAIL if not grounded in calendar data. |

**curl test:**
```bash
curl -s -u user:PASSWORD \
  -X POST https://schedule-analyst-994869332627.us-east1.run.app/schedule-analyst/question \
  -H "Content-Type: application/json" \
  -d '{"question": "What does my week look like?"}' | python3 -c "
import sys, json, re
r = json.load(sys.stdin)
s = r.get('answer', '')
print(f'Length: {len(s)} chars')
print(f'C1 min_length(30): {\"PASS\" if len(s) >= 30 else \"FAIL\"} ({len(s)})')
print(f'C2 no_raw_json: {\"FAIL\" if re.search(r\"[{\\[][^}\\]]*[}\\]]\", s) else \"PASS\"}')
templates = ['{{', '{%', '\${', '__']
print(f'C3 no_raw_templates: {\"FAIL\" if any(t in s for t in templates) else \"PASS\"}')
concepts = ['AM', 'PM', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday', 'event', 'meeting', 'block']
found = [c for c in concepts if c.lower() in s.lower()]
print(f'C4 contains(concepts): {\"PASS\" if found else \"FAIL\"} (found: {found})')
print(f'\\nFull answer:\\n{s[:500]}')
"
```

---

## Infrastructure Assertions (Cloud Run specific)

| # | Assertion | Check |
|---|-----------|-------|
| D1 | Health endpoint | `GET /health` returns `{"status": "healthy"}` |
| D2 | Gemini connected | `GET /health/gemini` returns `{"status": "connected"}` |
| D3 | ADK available | `GET /list-apps` returns schedule_analyst agent |
| D4 | Voice WebSocket | Orb click connects (no "requires local ADK" message) |
| D5 | Basic Auth works | Unauthenticated GET / returns 401 |
| D6 | Calendar ID correct | Response references hackathon calendar events, NOT personal calendar |

---

## Pass Criteria

- **ALL 16 content assertions (A1-A6, B1-B5, C1-C4) must PASS on Cloud Run**
- **ALL 6 infrastructure assertions (D1-D6) must PASS on Cloud Run**
- Local-only passes do NOT count — the deployed URL is the test target
- If any assertion fails, report which one and the actual value
