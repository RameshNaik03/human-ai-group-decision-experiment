# AI Usage Log

## Tools & models

| Tool / agent | Model | Used for |
|---|---|---|
| Claude (claude.ai, agentic mode with a cloud workspace: file editing, shell, headless browser) | **Claude Opus 5.5** (`claude-opus-5-5`) | Reading the brief, planning, architecture, writing all code, testing, README |
| VS Code | n/a | Reviewing code, running the project locally, final edits, pushing to GitHub |
| Claude Code (VS Code extension, agentic: file read/edit, PowerShell, Docker) | **Claude Opus 5.5** (`claude-opus-5-5`) | Prompt 4: voting UX, waiting-room timeout, disconnect robustness, Windows docs, Docker verification |

> Add a row here for any other assistant you use (e.g. Copilot inside VS Code) and log its prompts below.

## Workflow summary

1. Shared the assessment PDF/markdown with Claude and asked for a feasibility check and plan (3-hour budget).
2. Claude proposed an architecture, a list of design decisions for the open-ended parts
   (blind condition, tie-breaking, feedback, AI behavior) and a time plan. Reviewed it, then asked it to build.
3. Asked it not to push any code and that I would use VS Code; Claude built the repo locally in its workspace.
4. Claude verified the work itself:
   - scripted WebSocket clients ran full sessions for **all three conditions** (fast timings config),
   - a run against a real **PostgreSQL 16** checked that sessions/messages/votes are stored,
   - unit check of the **tie-break** logic (majority, round-1 tie-break, random draw, zero votes),
   - a **headless Chromium** run clicked through intro → waiting → chat → vote → feedback → results.
   - It could not run `docker compose` in its workspace (Docker Hub blocked), so the first Docker run was done locally.
5. I downloaded the project, opened it in VS Code, ran `docker compose up --build`, tested, and pushed.

## Prompts (verbatim, in order)

### Prompt 1 (Claude Opus 5.5, with the assessment file attached)
```
@"technical-assessment-multi-participant-human-ai-experiment-platform-v4.md" we gotta do this assignment in 3 hours is it possible to do this we have every right to do and implement read it carefully and let me know what we can do
```

### Prompt 2
```
let's begin the work now not more than 3 hours
```

### Prompt 3 (sent while Claude was working)
```
don't push any code until the assignment completes
i would like  use the vs code
```

### Prompt 4 (Claude Code in VS Code – Claude Opus 5.5, `claude-opus-5-5`)
```
You are working in my repository `chm-experiment`, my submission for a technical assessment:
a 3-participant real-time group decision experiment (React + FastAPI WebSockets + PostgreSQL,
Docker Compose). Read README.md, config.yml, docker-compose.yml, backend/app/*.py and
frontend/src/App.jsx before changing anything.

ASSESSMENT REQUIREMENTS (must all stay satisfied):
- 3 participants shown as Player A/B/C; participants must NOT be able to tell humans from AI (blind condition).
- Waiting room until all human slots are filled, then the experiment starts.
- 2 rounds of ~1 min text discussion; vote at the end of each round for who should be "Decision Maker";
  final result shown to everyone.
- Conditions switchable via config.yml only: 3 humans / 2 humans + 1 AI / 1 human + 2 AI.
- Whole app starts with one command: `docker compose up --build`.
- README explains how to run, switch configs, and design decisions/trade-offs.
- ai_prompts.md logs ALL prompts plus exact models/tools used.

The app already works end to end. Do NOT rewrite the architecture. Make small, focused changes only:

1. VOTING UX: players sometimes miss the 20s vote window (seen in testing: only 1-2 of 3 votes counted).
   - Make the voting phase very noticeable in the UI (highlight, short notice when voting starts;
     update document.title e.g. "Vote now!" so background tabs notice).
   - Raise vote_duration_sec in config.yml to 30.
   - Keep "no vote = abstention" and show it on the results table (e.g. "1 abstention").
   Must not reveal who is human or AI.

2. WAITING ROOM TIMEOUT: add `waiting_timeout_sec` (default 300) to config.yml. If the session hasn't
   started by then, tell the waiting human "Not enough participants joined, please try again later"
   and close the connection. Do not show how many humans are needed or joined.

3. ROBUSTNESS: handle a human disconnecting mid-session without crashing (they abstain). Make sure
   that if every human leaves, the session is cleaned up. Check that AI agent tasks are always cancelled.

4. WINDOWS FRIENDLINESS: in README, add PowerShell examples for switching conditions
   (`$env:CONDITION="one_human_two_ai"; docker compose up`) next to the bash ones, and a
   "Troubleshooting" section (Docker Desktop not running, port 3000/8000 busy, `service "db" is not running`).

5. VERIFY: after changes, run `docker compose up --build` and walk me through testing all 3 conditions.
   Fix any errors you find. Do not change behavior that already works.

6. DOCS: update README "Key design decisions" and "Trade-offs" to reflect your changes, and append this
   prompt plus a short summary of what you changed to ai_prompts.md, including the exact tool and model
   you are (e.g. "GitHub Copilot Agent – GPT-x" or "Claude Code – Claude ...").

RULES:
- Do NOT run git push or create commits. I will review and push myself.
- Never send participant types (human/ai) to the frontend.
- Keep changes minimal and readable; explain each change in one or two lines when done.
```

**What Claude Code changed (summary):**
- `config.yml` / `config.py`: `vote_duration_sec` 20 → 30; new `waiting_timeout_sec: 300` (`0` = off).
- `session.py`:
  - Per-human waiting-room timeout task sends `{"type":"timeout"}` with the fixed message (no counts) and closes the socket.
  - AI tasks are now stored on the session and always cancelled in a `finally` (previously, cancelling a session mid-round left them running).
  - Sockets are removed only if the slot still belongs to that socket, so a freed and reused slot is never closed by mistake.
  - `SessionManager.leave()` prunes empty finished or waiting sessions right away.
- `main.py`: calls `manager.leave(...)`; also catches the `RuntimeError` Starlette raises when receiving after a server-side close.
- `App.jsx` / `styles.css`:
  - Voting phase: "time to vote" chat line, pulsing banner with countdown, highlighted vote panel that scrolls into view, flashing "🗳️ Vote now!" tab title until you vote.
  - Abstention count in round feedback and a "No vote" column on the results table.
  - Timeout screen with "Try again".
- `README.md`: PowerShell examples, Troubleshooting section, updated design decisions and trade-offs.
- Verification:
  - `docker compose up --build` builds and starts cleanly.
  - An in-process scenario test (real uvicorn plus scripted WebSocket players, fast timings, run inside the backend image) passed **33/33** checks:
    - full sessions in all 3 conditions with an abstention,
    - no `human`/`ai` in any payload,
    - one human leaving in discussion or voting,
    - every human leaving (session removed, no AI tasks left),
    - waiting-room timeout,
    - rejoin after leaving.

<!-- Append every further prompt below, in order, with the tool/model used. -->
