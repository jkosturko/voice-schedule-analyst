# LinkedIn Post — Voice Schedule Analyst

**For posting after competition submission.**

---

I built a voice-first AI calendar analyst for the Gemini Live Agent Challenge — and the experience reshaped how I think about agent design.

The premise: what if your calendar assistant actually *talked* to you? Not read a list of events, but briefed you like a chief of staff — "Your morning has a conflict between deep work and your 1:1, and you've got four back-to-back meetings that'll drain you by 3pm."

The interesting part wasn't the voice integration. It was building the analysis layer underneath — conflict detection, dead time identification, back-to-back fatigue warnings, and schedule optimization. The agent doesn't just read your calendar. It reasons about it.

Built with Google ADK + Gemini Live API, deployed on Cloud Run, connected to real Google Calendar data. Open source:

https://github.com/jkosturko/voice-schedule-analyst

Key takeaway: voice changes the UX contract. When an agent speaks, it has to lead with what matters — no scrolling, no skimming. That constraint actually produces better analysis.

Feedback welcome — especially from anyone building with ADK or the Live API.

#GeminiLiveAgentChallenge #GoogleADK #AIAgents #AppliedAI #VoiceAI
