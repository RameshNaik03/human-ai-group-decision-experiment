# Multi-Participant Human-AI Group Decision Experiment

A lightweight real-time platform for a **3-participant group decision experiment**: participants
(Player A/B/C — humans or AI agents, blind) chat for 2 rounds and vote on who should be the
**Decision Maker**.

**Stack:** React (Vite) · FastAPI (WebSockets) · PostgreSQL · Docker Compose

---

## Quick start

```bash
docker compose up --build
```

Open **http://localhost:3000**. Each browser tab is one human participant: open as many tabs as
the condition has human slots (use separate windows side by side for the 3-human condition).

| Service  | URL                    |
|----------|------------------------|
| App      | http://localhost:3000  |
| Backend  | http://localhost:8000/api/health |
| Postgres | `docker compose exec db psql -U chm experiment` |

## Switching conditions

All experiment parameters live in [`config.yml`](config.yml). Three conditions are predefined:

| `active_condition`   | Participants          | Tabs to open |
|----------------------|-----------------------|--------------|
| `three_humans`       | human, human, human   | 3 |
| `two_humans_one_ai`  | human, human, ai      | 2 |
| `one_human_two_ai`   | human, ai, ai         | 1 |

Either edit `active_condition` and run `docker compose restart backend` (config is mounted, no
rebuild needed), **or** override at start-up without touching the file:

```bash
# bash / Git Bash / macOS / Linux
CONDITION=one_human_two_ai docker compose up --build
```

```powershell
# Windows PowerShell
$env:CONDITION="one_human_two_ai"; docker compose up --build
# the variable stays set for this PowerShell window; to go back to config.yml:
Remove-Item Env:CONDITION
```

Valid values: `three_humans`, `two_humans_one_ai`, `one_human_two_ai`.

Round length, voting window, number of rounds, intermediate feedback, label shuffling, waiting-room
timeout and AI settings are configurable in the same file.

### Optional: LLM-powered AI agents

By default AI agents are **rule-based** (no API key needed, so the demo always works). To use an LLM:

```bash
cp .env.example .env        # add OPENAI_API_KEY or ANTHROPIC_API_KEY
# config.yml -> ai.provider: openai   (or anthropic)
docker compose up --build
```

If the key is missing or a call fails, the agent silently falls back to the rule-based policy.

---

## How it works

```
Browser (React) ──WebSocket /ws──▶ nginx ──▶ FastAPI
                                             ├─ SessionManager  (waiting room / matching)
                                             ├─ Session         (state machine + server-side timers)
                                             ├─ AIAgent         (LLM or rule-based participant)
                                             └─ db.py ──▶ PostgreSQL (sessions, messages, votes)
```

Session flow (server-driven):
`waiting (≤300s) → [matching delay] → (discussion 60s → voting ≤30s → feedback 6s) × 2 → final results`

## Key design decisions

**Blind condition**
- Participant types exist only server-side; the client never receives `human`/`ai` (not in the
  WebSocket payloads, not in `/api/settings`).
- `shuffle_labels: true` randomizes which letter the AI gets, so it is not always "Player C".
- AI messages get a simulated reading + typing delay (based on message length), are short and
  casual, are capped per round, and AI↔AI replies are throttled to avoid instant ping-pong.
- AI votes arrive after a random delay, not instantly.
- **Matching delay:** after the room fills, the start is delayed by a random 3–8 s. Otherwise in
  the 1-human condition the session would start instantly, which hints that the others are bots.
- The waiting room does **not** show "1/2 humans joined" counters, since that would reveal the
  number of humans.
- **Waiting-room timeout** (`waiting_timeout_sec`, default 300 s, `0` = off): each human's own timer
  starts when they join. If the session hasn't started by then, they see "Not enough participants
  joined, please try again later" and the connection is closed. The message contains no counts. A
  timer that fires during the matching delay waits for it to finish, so a filling room is never broken up.
- Disconnects are not announced (AI agents never leave, so an announcement would reveal humanness).
- The AI never claims to be human; if asked, it deflects and steers back to the task.
  (A real study would include a debriefing.)

**Rounds, voting and feedback**
- Server owns all timers; clients just render a countdown, so there's no clock drift between players.
- Chat is only enabled during discussion; voting happens at the end of each round.
- Voting ends early once all active participants have voted (or after the timeout); not voting = abstention.
- **Voting is hard to miss** (testers sometimes missed the old 20 s window): the window is now 30 s; when
  voting starts, a "time to vote" line is added to the chat, a pulsing banner with the countdown appears,
  the vote panel is highlighted and scrolled into view, and the browser tab title flashes
  "🗳️ Vote now!" until you vote, so a background tab also notices. The same UI is shown to everyone.
- Abstentions are shown as a **count only** ("1 abstention") in the round feedback and the results
  table, never *who* abstained. It is derived on the client from the tally (3 − votes cast).
- **Disconnects:** a human who leaves mid-session just abstains; the others continue. If every human
  leaves, the session task is cancelled, all AI agent tasks are cancelled (always, in a `finally`), and
  the session is removed from memory right away. Waiting rooms that everyone left are removed too.
- Self-voting is allowed (volunteering to be Decision Maker is a legitimate choice).
- **Intermediate feedback:** after round 1, everyone sees the anonymous vote tally, which gives
  round 2 something to discuss (configurable via `show_intermediate_results`).

**Final decision & tie-breaking**
1. The **final round's votes** decide.
2. Tie → the earlier round's votes among the tied candidates.
3. Still tied → random draw (server-side). The method used is shown to participants and stored.

**AI agent behaviour**
- *Rule-based (default):* has a preferred candidate (possibly itself), responds to direct mentions
  and questions, deflects "are you a bot?" questions, and shows mild conformity (65% chance to
  adopt the round-1 leader in round 2), plus being swayed by repeated mentions in chat.
- *LLM mode:* the full transcript (plus round-1 tally) goes to the model with a persona prompt
  (one short casual sentence, may output `[skip]` to stay quiet). Votes are a single-letter LLM answer.

**Data**
Postgres stores `sessions` (condition, true participant types, winner, method, tallies),
`messages`, and `votes` with timestamps for later analysis. Live state stays in memory. DB writes
are best-effort so a DB hiccup never breaks a running session.

## Trade-offs / known limitations (time-boxed)

- Live state is in memory with a single backend process: no horizontal scaling, and a backend restart drops running sessions.
- No reconnection: a refreshed tab is a new participant. A disconnected human simply abstains.
- No authentication / Prolific-style participant IDs, consent screen or admin dashboard.
- The waiting-room timeout is per human, not per session. Someone who joins late gets their full
  300 s, but an early joiner may be sent home just before the room would have filled.
- Abstentions only come from humans (AI agents always vote). The count never says *who* abstained,
  but over many sessions "abstentions happen" is a weak hint that humans are present. Making AI
  agents occasionally abstain would hide this, but it would change the AI behaviour, so it was left out.
- The flashing tab title only helps if the tab is still open. There are no sound or OS notifications
  (they need extra permissions and behave differently in each browser).
- No automated test suite in the repo; logic was verified with scripted WebSocket clients for all
  three conditions (including disconnects, everyone leaving, and waiting-room timeouts), a
  headless-browser run, and tie-break checks (see `ai_prompts.md`).

## Troubleshooting

**Docker Desktop is not running**
`error during connect ... //./pipe/dockerDesktopLinuxEngine: The system cannot find the file specified`
(or `Cannot connect to the Docker daemon`). Start Docker Desktop, wait until it says *Engine running*,
then check with `docker info` and run `docker compose up --build` again.

**Port 3000 or 8000 is already in use**
`Bind for 0.0.0.0:3000 failed: port is already allocated`. Find and stop the process using it:

```powershell
# PowerShell
Get-NetTCPConnection -LocalPort 3000 -State Listen | Select-Object OwningProcess
Stop-Process -Id <PID>
```
```bash
# bash / macOS / Linux
lsof -i :3000        # then: kill <PID>
```

You can also change the host side of the mapping in `docker-compose.yml`, e.g. `"3001:80"`, and open
http://localhost:3001. An old copy of this stack can also hold the ports, so run `docker compose down` first.

**`service "db" is not running`**
This appears when you run `docker compose exec db ...` (e.g. the `psql` command above) while the stack
is not up. Start it first (`docker compose up -d`), then check with `docker compose ps` that `db` is
`healthy`. If `db` keeps restarting, look at `docker compose logs db`. As a last resort,
`docker compose down -v` resets the database volume. **This deletes all stored experiment data.**

**Condition doesn't change**
In PowerShell, `$env:CONDITION` stays set for the whole window and overrides `config.yml`. Run
`Remove-Item Env:CONDITION`. After editing `config.yml`, restart the backend: `docker compose restart backend`.

## Project structure

```
config.yml               experiment configuration (conditions, timings, AI)
docker-compose.yml       db + backend + frontend
backend/app/main.py      FastAPI app, WebSocket endpoint
backend/app/session.py   session state machine, matching, voting, tie-breaking
backend/app/ai_agent.py  AI participant (LLM + rule-based fallback)
backend/app/config.py    YAML loading & validation
backend/app/db.py        SQLAlchemy models & persistence
frontend/src/App.jsx     all UI screens (intro, waiting, chat, voting, results)
ai_prompts.md            AI usage log
```

## Local development without Docker

```bash
# backend (runs without a DB if DATABASE_URL is unset)
cd backend && pip install -r requirements.txt
CONFIG_PATH=../config.yml uvicorn app.main:app --reload --port 8000

# frontend (proxies /ws and /api to :8000)
cd frontend && npm install && npm run dev   # http://localhost:5173
```
