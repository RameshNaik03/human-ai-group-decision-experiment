"""Session lifecycle: waiting room -> (discussion -> voting) x N rounds -> results.

The server owns all timers and state. Participant types (human/ai) live only in
`Session.types` and are never sent to clients (blind condition)."""
import asyncio
import logging
import random
import time
import uuid

from fastapi import WebSocket

from . import db
from .ai_agent import AIAgent
from .config import Config

log = logging.getLogger("session")

MAX_MESSAGE_LEN = 300


class Session:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.id = uuid.uuid4().hex[:10]
        types = list(cfg.participant_types)
        if cfg.shuffle_labels:
            random.shuffle(types)
        self.types: dict[str, str] = dict(zip(cfg.labels, types))  # NEVER sent to clients
        self.human_slots = [l for l, t in self.types.items() if t == "human"]
        random.shuffle(self.human_slots)

        self.sockets: dict[str, WebSocket] = {}
        self.state = "waiting"          # waiting | starting | running | finished
        self.phase: str | None = None   # discussion | voting | break
        self.round = 0
        self.messages: list[dict] = []
        self.votes: dict[int, dict[str, str]] = {}
        self.tallies: list[dict[str, int]] = []
        self.vote_event = asyncio.Event()
        self.agents: list[AIAgent] = []
        self.ai_tasks: list[asyncio.Task] = []               # current AI discuss/vote tasks
        self.wait_tasks: dict[str, asyncio.Task] = {}        # per-human waiting-room timeouts
        self.task: asyncio.Task | None = None

    # ------------------------------------------------------------------ joining
    def free_slots(self) -> list[str]:
        return [l for l in self.human_slots if l not in self.sockets]

    @property
    def is_open(self) -> bool:
        return self.state == "waiting" and bool(self.free_slots())

    async def add_human(self, ws: WebSocket) -> str:
        label = self.free_slots()[0]
        self.sockets[label] = ws
        await self.send(label, {"type": "welcome", "you": label, "settings": self.cfg.public()})
        await self.send(label, {"type": "waiting"})
        log.info("[%s] human joined as %s (%d/%d)", self.id, label, len(self.sockets), len(self.human_slots))
        if self.cfg.waiting_timeout_sec > 0:
            self.wait_tasks[label] = asyncio.create_task(self._waiting_timeout(label, ws))
        if not self.free_slots():
            self.state = "starting"
            self.task = asyncio.create_task(self._run_safe())
        return label

    async def _waiting_timeout(self, label: str, ws: WebSocket):
        """Send a human home if the session has not started after `waiting_timeout_sec`.
        The message deliberately says nothing about how many people are needed/joined."""
        await asyncio.sleep(self.cfg.waiting_timeout_sec)
        while self.state == "starting":     # room just filled, matching delay running
            await asyncio.sleep(1)
        if self.state != "waiting" or self.sockets.get(label) is not ws:
            return
        self.wait_tasks.pop(label, None)
        self.sockets.pop(label, None)
        log.info("[%s] %s waiting-room timeout", self.id, label)
        try:
            await ws.send_json({"type": "timeout",
                                "message": "Not enough participants joined, please try again later."})
            await ws.close(code=1000)
        except Exception:
            pass

    async def disconnect(self, label: str, ws: WebSocket | None = None):
        # Only free the slot if it still belongs to this socket (it may already have been
        # freed by a failed send / timeout and handed to a new participant).
        if ws is None or self.sockets.get(label) is ws:
            self.sockets.pop(label, None)
            wait = self.wait_tasks.pop(label, None)
            if wait:
                wait.cancel()
        log.info("[%s] %s disconnected (state=%s)", self.id, label, self.state)
        if self.state == "running":
            if not self.sockets:
                self.state = "finished"     # nobody left to run the experiment for
                if self.task:
                    self.task.cancel()      # _run_safe's finally cancels the AI tasks
            else:
                self._check_all_voted()     # the leaver simply abstains

    # ---------------------------------------------------------------- messaging
    async def send(self, label: str, payload: dict):
        ws = self.sockets.get(label)
        if ws is None:
            return
        try:
            await ws.send_json(payload)
        except Exception:
            if self.sockets.get(label) is ws:
                self.sockets.pop(label, None)

    async def broadcast(self, payload: dict):
        await asyncio.gather(*(self.send(l, payload) for l in list(self.sockets)))

    async def handle(self, label: str, data: dict):
        kind = data.get("type")
        if kind == "chat":
            text = str(data.get("text", "")).strip()[:MAX_MESSAGE_LEN]
            if text and self.state == "running" and self.phase == "discussion":
                await self.add_message(label, text)
        elif kind == "vote":
            await self.record_vote(label, str(data.get("target", "")))

    async def add_message(self, label: str, text: str):
        msg = {"from": label, "text": text, "round": self.round, "ts": time.time()}
        self.messages.append(msg)
        await self.broadcast({"type": "chat", **msg})
        for agent in self.agents:
            agent.notify()
        await db.save_message(self.id, self.round, label, text)

    async def record_vote(self, voter: str, target: str):
        if self.state != "running" or self.phase != "voting":
            return
        if target not in self.cfg.labels or voter in self.votes[self.round]:
            return
        self.votes[self.round][voter] = target
        await self.send(voter, {"type": "vote_ack", "round": self.round, "target": target})
        await db.save_vote(self.id, self.round, voter, target)
        self._check_all_voted()

    def _check_all_voted(self):
        if self.phase != "voting":
            return
        expected = {l for l, t in self.types.items() if t == "ai"} | set(self.sockets)
        if expected <= set(self.votes.get(self.round, {})):
            self.vote_event.set()

    # ------------------------------------------------------------------ game loop
    async def _run_safe(self):
        try:
            await self.run()
        except asyncio.CancelledError:
            log.info("[%s] session cancelled", self.id)
        except Exception:
            log.exception("[%s] session crashed", self.id)
            self.state = "finished"
            await self.broadcast({"type": "error", "message": "Something went wrong. Please contact the experimenter."})
        finally:
            self._cancel_ai_tasks()     # never leave AI agents running after the session ends

    def _cancel_ai_tasks(self):
        for t in self.ai_tasks:
            t.cancel()
        self.ai_tasks = []

    async def run(self):
        # Artificial matching delay: in the 1-human condition the room would otherwise
        # fill instantly, which hints that the others are not humans.
        await asyncio.sleep(random.uniform(*self.cfg.matching_delay_sec))
        if self.free_slots():           # someone left during the delay
            self.state = "waiting"
            return

        self.state = "running"
        for t in self.wait_tasks.values():
            t.cancel()
        self.wait_tasks.clear()
        self.agents =[AIAgent(l, self) for l, t in self.types.items() if t == "ai"]
        await db.save_session_start(self.id, self.cfg.condition, self.types, self.cfg.public())
        log.info("[%s] start, condition=%s types=%s", self.id, self.cfg.condition, self.types)

        for rnd in range(1, self.cfg.rounds + 1):
            self.round = rnd

            # --- discussion
            self.phase = "discussion"
            await self.broadcast({"type": "phase", "phase": "discussion", "round": rnd,
                                  "rounds": self.cfg.rounds, "seconds": self.cfg.round_duration_sec})
            self.ai_tasks = [asyncio.create_task(a.discuss(rnd)) for a in self.agents]
            await asyncio.sleep(self.cfg.round_duration_sec)
            self._cancel_ai_tasks()

            # --- voting
            self.votes[rnd] = {}
            self.vote_event.clear()
            self.phase = "voting"
            await self.broadcast({"type": "phase", "phase": "voting", "round": rnd,
                                  "rounds": self.cfg.rounds, "seconds": self.cfg.vote_duration_sec})
            self.ai_tasks = [asyncio.create_task(a.vote(rnd)) for a in self.agents]
            try:
                await asyncio.wait_for(self.vote_event.wait(), timeout=self.cfg.vote_duration_sec)
            except asyncio.TimeoutError:
                pass
            self._cancel_ai_tasks()
            self.tallies.append(self.tally(rnd))

            # --- intermediate feedback
            if rnd < self.cfg.rounds:
                self.phase = "break"
                await self.broadcast({
                    "type": "phase", "phase": "break", "round": rnd, "rounds": self.cfg.rounds,
                    "seconds": self.cfg.between_rounds_sec,
                    "tally": self.tallies[-1] if self.cfg.show_intermediate_results else None,
                })
                await asyncio.sleep(self.cfg.between_rounds_sec)

        winner, method = self.decide()
        self.state, self.phase = "finished", "results"
        await self.broadcast({"type": "final", "winner": winner, "method": method, "tallies": self.tallies})
        await db.save_result(self.id, winner, method, self.tallies)
        log.info("[%s] finished: winner=%s (%s)", self.id, winner, method)

    # -------------------------------------------------------------------- results
    def tally(self, rnd: int) -> dict[str, int]:
        counts = {l: 0 for l in self.cfg.labels}
        for target in self.votes.get(rnd, {}).values():
            counts[target] += 1
        return counts

    def decide(self) -> tuple[str, str]:
        """Final round votes decide. Ties -> earlier rounds' votes (latest first) -> random draw."""
        final = self.tallies[-1]
        top = max(final.values())
        tied = [l for l, c in final.items() if c == top]
        if len(tied) == 1:
            return tied[0], "majority of final-round votes"
        for idx in range(len(self.tallies) - 2, -1, -1):
            earlier = self.tallies[idx]
            best = max(earlier[l] for l in tied)
            narrowed = [l for l in tied if earlier[l] == best]
            if len(narrowed) == 1:
                return narrowed[0], f"tie broken by round {idx + 1} votes"
            tied = narrowed
        return random.choice(tied), "tie broken by random draw"


class SessionManager:
    """Puts each arriving human into the first session with a free slot."""

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.sessions: dict[str, Session] = {}
        self.lock = asyncio.Lock()

    def _prune(self):
        """Drop sessions nobody is connected to anymore (finished, or abandoned in the waiting room)."""
        for sid in [s.id for s in self.sessions.values() if not s.sockets and s.state in ("waiting", "finished")]:
            del self.sessions[sid]

    async def leave(self, session: Session, label: str, ws: WebSocket):
        await session.disconnect(label, ws)
        async with self.lock:
            self._prune()

    async def join(self, ws: WebSocket) -> tuple[Session, str]:
        async with self.lock:
            self._prune()
            session = next((s for s in self.sessions.values() if s.is_open), None)
            if session is None:
                session = Session(self.cfg)
                self.sessions[session.id] = session
            label = await session.add_human(ws)
        return session, label
