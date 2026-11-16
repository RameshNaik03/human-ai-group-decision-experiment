# AI Usage Log

## Tools & models

| Tool / agent | Model | Used for |
|---|---|---|
| Claude (claude.ai, agentic mode with a cloud workspace: file editing, shell, headless browser) | **Claude Opus 5.5** (`claude-opus-5-5`) | Reading the brief, planning, architecture, writing all code, testing, README |
| Claude Code (VS Code extension) | **Claude Opus 5.5** (`claude-opus-5-5`) | Second iteration (Prompt 15) and final repo cleanup (Prompt 43) |
| VS Code | n/a | Reviewing code, running the project locally, final edits, pushing to GitHub |

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
5. Downloaded the project, opened it in VS Code, ran `docker compose up --build` and played a full session; testing showed votes being missed in the 20 s window.
6. Asked Claude (claude.ai) to write an improvement prompt and ran it in Claude Code (Prompt 15): voting UX, waiting-room timeout, robustness fixes, Windows docs, 33/33 scenario checks.
7. Shared Claude Code's report back with Claude for review; Claude cloned the public GitHub repo and re-tested all three conditions.
8. Pushed to GitHub, renamed the repo, and used Claude Code to clean up the repo and finish this log (Prompt 43).

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

### Prompt 4 (Claude Opus 5.5, claude.ai)
```
what is next
```

### Prompt 5
```
i have the file in vs code
```

### Prompt 6
```
how do i run this in vs code
```

### Prompt 7
```
docker runns successfully i think
```

### Prompt 8
```
[pasted the `docker compose up` terminal output: frontend/backend startup logs]
```

### Prompt 9 (pasted a line the AI player wrote in the chat)
```
what do you think the decision maker will have to do?
```

### Prompt 10
```
i am getting responeses from player a
```

### Prompt 11
```
[screenshot of the Results screen: Player B elected, round tallies A0/B1/C0 and A0/B2/C0]
```

### Prompt 12
```
[pasted PowerShell output: `service "db" is not running`]
```

### Prompt 13
```
[pasted backend restart logs]
```

### Prompt 14
```
give me a prompt to fix and complete the work of the whole assessment
```
→ Claude wrote the improvement prompt below, which I then ran in Claude Code (Prompt 15).

### Prompt 15 (Claude Code in VS Code – Claude Opus 5.5, `claude-opus-5-5`)
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

### Prompt 16 (Claude Opus 5.5, claude.ai)
```
[shared Claude Code's completion report (attachment) back with Claude for review]
```

### Prompt 17
```
[pasted the list of prompts 4–15 for this log] shall i submit this code now to claude
```

### Prompt 18
```
[pasted `git status` output: nothing to commit, working tree clean]
```

### Prompt 19
```
[pasted `git log --oneline` / `git ls-files` output]
```

### Prompt 20 (quoted Claude's instruction)
```
1. Create a public repo at https://github.com/new named `chm-experiment`, with nothing else added.
```

### Prompt 21
```
how do i do this
```

### Prompt 22
```
i dont see anything after pressing ctrl and shift and g
```

### Prompt 23
```
[pasted terminal prompt]
```

### Prompt 24
```
[pasted `git remote -v` output (empty)]
```

### Prompt 25
```
[pasted `git remote add` usage error]
```

### Prompt 26
```
so the technical is complete now right ?
```

### Prompt 27
```
[uploaded a zip of the project] check one again is everything perfectly done or not ?
```

### Prompt 28
```
wait it's a wrong file
```

### Prompt 29
```
[uploaded the correct project zip]
```

### Prompt 30
```
[pasted the CHM invitation email] write a reply to this email
```

### Prompt 31
```
before submiting the email i would like to change the repo name ?
```

### Prompt 32
```
[pasted `git remote set-url` output with the placeholder URL NEW-NAME]
```

### Prompt 33
```
[pasted `git remote -v` output showing the placeholder YOUR-REAL-NAME]
```

### Prompt 34
```
[answered Claude's question: chose repo name "human-ai-group-decision"]
```

### Prompt 35
```
[pasted `git push` output: Repository not found]
```

### Prompt 36
```
rename changed in github
```

### Prompt 37
```
https://github.com/RameshNaik03/human-ai-group-decision-experiment
```

### Prompt 38
```
[pasted `git remote -v` output after set-url]
```

### Prompt 39
```
[pasted git output showing an untracked `chm-experiment/` folder]
```

### Prompt 40
```
[attached terminal log: `dir` of the duplicate chm-experiment folder]
```

### Prompt 41
```
[pasted Copy-Item error: ai_prompts.md not found in Downloads]
```

### Prompt 42
```
give me a promot and fix the issue and maitnain a clean repo
```

### Prompt 43 (Claude Code in VS Code – Claude Opus 5.5, `claude-opus-5-5`)
````
Finalize my assessment repo and keep it clean. Work only in this folder (the git repo root,
the one containing docker-compose.yml). Remote: https://github.com/RameshNaik03/human-ai-group-decision-experiment.git

TASK 1 – Remove the accidental duplicate
There is an untracked nested folder `chm-experiment/` inside the repo root. It is a stray copy of the
project (it even has its own .git). Confirm it is untracked (`git status`) and not referenced anywhere,
then delete it completely. Do not touch any other file or folder.

TASK 2 – Complete ai_prompts.md (the assessment requires ALL prompts, in order)
a) In the "Tools & models" table, add this row above the VS Code row:
   | Claude Code (VS Code extension) | **Claude Opus 5.5** (`claude-opus-5-5`) | Second iteration (Prompt 15) and final repo cleanup (Prompt 43) |
   Remove the line "> Add a row here for any other assistant..." if present.
b) Replace step 5 of "Workflow summary" with:
   5. Downloaded the project, opened it in VS Code, ran `docker compose up --build` and played a full session; testing showed votes being missed in the 20 s window.
   6. Asked Claude (claude.ai) to write an improvement prompt and ran it in Claude Code (Prompt 15): voting UX, waiting-room timeout, robustness fixes, Windows docs, 33/33 scenario checks.
   7. Shared Claude Code's report back with Claude for review; Claude cloned the public GitHub repo and re-tested all three conditions.
   8. Pushed to GitHub, renamed the repo, and used Claude Code to clean up the repo and finish this log (Prompt 43).
c) The existing heading "### Prompt 4 (Claude Code in VS Code – Claude Opus 5.5, `claude-opus-5-5`)" must become
   "### Prompt 15 (Claude Code in VS Code – Claude Opus 5.5, `claude-opus-5-5`)". Keep its content unchanged.
d) Directly ABOVE that Prompt 15 heading, insert prompts 4–14. Directly BELOW the Prompt 15 section (before the
   trailing "<!-- Append every further prompt ... -->" comment, keep that comment last), insert prompts 16–43.
   Format each one exactly like the existing entries: a "### Prompt N" heading (with the note in parentheses if given)
   followed by the text in a ``` code block. Text in [square brackets] describes a non-text input; keep it as written.

   Prompts 4–14 (Claude Opus 5.5, claude.ai):
   4  what is next
   5  i have the file in vs code
   6  how do i run this in vs code
   7  docker runns successfully i think
   8  [pasted the `docker compose up` terminal output: frontend/backend startup logs]
   9  what do you think the decision maker will have to do?   (note: pasted a line the AI player wrote in the chat)
   10 i am getting responeses from player a
   11 [screenshot of the Results screen: Player B elected, round tallies A0/B1/C0 and A0/B2/C0]
   12 [pasted PowerShell output: `service "db" is not running`]
   13 [pasted backend restart logs]
   14 give me a prompt to fix and complete the work of the whole assessment
      → after the code block add the line: "→ Claude wrote the improvement prompt below, which I then ran in Claude Code (Prompt 15)."

   Prompts 16–42 (Claude Opus 5.5, claude.ai):
   16 [shared Claude Code's completion report (attachment) back with Claude for review]
   17 [pasted the list of prompts 4–15 for this log] shall i submit this code now to claude
   18 [pasted `git status` output: nothing to commit, working tree clean]
   19 [pasted `git log --oneline` / `git ls-files` output]
   20 1. Create a public repo at https://github.com/new named `chm-experiment`, with nothing else added.   (note: quoted Claude's instruction)
   21 how do i do this
   22 i dont see anything after pressing ctrl and shift and g
   23 [pasted terminal prompt]
   24 [pasted `git remote -v` output (empty)]
   25 [pasted `git remote add` usage error]
   26 so the technical is complete now right ?
   27 [uploaded a zip of the project] check one again is everything perfectly done or not ?
   28 wait it's a wrong file
   29 [uploaded the correct project zip]
   30 [pasted the CHM invitation email] write a reply to this email
   31 before submiting the email i would like to change the repo name ?
   32 [pasted `git remote set-url` output with the placeholder URL NEW-NAME]
   33 [pasted `git remote -v` output showing the placeholder YOUR-REAL-NAME]
   34 [answered Claude's question: chose repo name "human-ai-group-decision"]
   35 [pasted `git push` output: Repository not found]
   36 rename changed in github
   37 https://github.com/RameshNaik03/human-ai-group-decision-experiment
   38 [pasted `git remote -v` output after set-url]
   39 [pasted git output showing an untracked `chm-experiment/` folder]
   40 [attached terminal log: `dir` of the duplicate chm-experiment folder]
   41 [pasted Copy-Item error: ai_prompts.md not found in Downloads]
   42 give me a promot and fix the issue and maitnain a clean repo

   Prompt 43 (Claude Code in VS Code – Claude Opus 5.5, `claude-opus-5-5`):
   43 this entire prompt, verbatim, followed by a 3–5 line summary of what you did.

TASK 3 – Repo hygiene
- Make sure .gitignore covers: node_modules/, dist/, __pycache__/, *.pyc, .env, .venv/, .DS_Store, .vscode/
- Check `git ls-files` contains no node_modules, dist, __pycache__, .env or nested project copies.
- config.yml must have `active_condition: two_humans_one_ai`. Do not change any other code or behavior.

TASK 4 – Verify, commit, push (I authorize pushing for this task)
- `git remote -v` must point to https://github.com/RameshNaik03/human-ai-group-decision-experiment.git; fix it if not.
- `git status` must show only ai_prompts.md (and .gitignore if changed) as modified, nothing untracked.
- Show me `git diff --stat`, then commit with the message "Complete AI usage log and clean repo" and run `git push origin main`.
- Finally run `git status` and `git log --oneline -3` and report the results, plus the number of "### Prompt" headings in ai_prompts.md (expected 43).
````

**What Claude Code did (summary):**
- Task 1: `git status` was clean, and the only copy of the project on disk is this repo. The nested `chm-experiment/` duplicate no longer existed, so nothing was deleted.
- Task 2: completed this log. Added prompts 4–14 and 16–43, renumbered the earlier Claude Code prompt to 15, updated the tools table and the workflow summary.
- Task 3: `.gitignore` already covered every required pattern. `git ls-files` has no build output, secrets or nested copies, and `config.yml` uses `two_humans_one_ai`. No code changed.
- Task 4: checked the remote, then committed only `ai_prompts.md` as "Complete AI usage log and clean repo" and pushed it to `origin/main`.

<!-- Append every further prompt below, in order, with the tool/model used. -->
