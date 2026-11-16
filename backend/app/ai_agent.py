"""AI participant. Uses an LLM (OpenAI / Anthropic) if configured, otherwise a
rule-based policy. Either way it behaves like a casual human participant:
short messages, simulated typing delay, limited number of messages per round,
and it never volunteers that it is an AI."""
from __future__ import annotations

import asyncio
import logging
import os
import random
import re
from typing import TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    from .session import Session

log = logging.getLogger("ai")

SYSTEM_PROMPT = """You are Player {me} in an online group chat that is part of a study.
The participants are {players}. Everyone is anonymous.
Task: within the chat, the group must agree who among {players} should be elected
"Decision Maker" for a later (imaginary) task. At the end of each round everyone votes.

How to write:
- Write like an ordinary participant typing quickly: ONE short sentence (max ~20 words),
  casual, lowercase is fine, no emojis, no lists, no formal language.
- Refer to others as "A", "B", "C" or "player A" etc. Refer to yourself as "me"/"I".
- Have a mild opinion and be willing to be persuaded. Volunteering yourself is allowed.
- Do not bring up whether anyone is a human or an AI. If someone asks, deflect casually
  and steer back to the task.
- Output only the chat message text, without a "Player X:" prefix.
- If you have nothing useful to add right now, output exactly: [skip]"""


def _transcript(session: "Session") -> str:
    if not session.messages:
        return "(no messages yet)"
    return "\n".join(f"[round {m['round']}] Player {m['from']}: {m['text']}" for m in session.messages[-30:])


class AIAgent:
    def __init__(self, label: str, session: "Session"):
        self.label = label
        self.session = session
        self.cfg = session.cfg.ai
        self.labels = session.cfg.labels
        self.favorite = random.choice(self.labels)    # rule-based: current preferred candidate
        self.used: set[str] = set()
        self._event = asyncio.Event()

        provider = str(self.cfg.get("provider", "rule_based")).lower()
        key_env = {"openai": "OPENAI_API_KEY", "anthropic": "ANTHROPIC_API_KEY"}.get(provider)
        self.api_key = os.getenv(key_env) if key_env else None
        if key_env and not self.api_key:
            log.warning("%s not set - AI %s falls back to rule_based", key_env, label)
        self.provider = provider if self.api_key else "rule_based"

    def notify(self):
        self._event.set()

    # ------------------------------------------------------------- discussion
    async def discuss(self, rnd: int):
        max_msgs = int(self.cfg.get("max_messages_per_round", 3))
        await asyncio.sleep(random.uniform(*self.cfg.get("first_message_delay_sec", [4, 12])))
        if rnd > 1:
            self._update_favorite_after_round(rnd - 1)

        sent, seen, first = 0, len(self.session.messages), True
        while sent < max_msgs:
            if not first:
                self._event.clear()
                try:
                    await asyncio.wait_for(self._event.wait(), timeout=random.uniform(12, 20))
                except asyncio.TimeoutError:
                    pass
                new = [m for m in self.session.messages[seen:] if m["from"] != self.label]
                seen = len(self.session.messages)
                if not new and random.random() < 0.5:
                    continue                            # quiet chat: don't always fill the silence
                if new and all(self.session.types[m["from"]] == "ai" for m in new) and random.random() < 0.6:
                    continue                            # avoid AI<->AI ping-pong
                await asyncio.sleep(random.uniform(1, 3))  # "reading" time
            first = False

            text = await self._generate(rnd)
            seen = len(self.session.messages)
            if not text:
                continue
            speed = float(self.cfg.get("typing_speed_chars_per_sec", 12))
            await asyncio.sleep(min(len(text) / speed, 8) + random.uniform(0.5, 1.5))
            await self.session.add_message(self.label, text)
            sent += 1

    async def _generate(self, rnd: int) -> str | None:
        if self.provider != "rule_based":
            try:
                prompt = (f"It is round {rnd} of {self.session.cfg.rounds}.{self._feedback_note()}\n"
                          f"Chat so far:\n{_transcript(self.session)}\n\nYour next message as Player {self.label}:")
                out = await self._llm(prompt, max_tokens=80)
                out = out.strip().strip('"').splitlines()[0] if out.strip() else ""
                out = re.sub(r"^(player\s*)?[A-C]\s*:\s*", "", out, flags=re.I)[:200]
                return None if (not out or "[skip]" in out.lower()) else out
            except Exception as e:
                log.warning("LLM call failed (%s), using rule-based reply", e)
        return self._rule_based_message(rnd)

    # ---------------------------------------------------------------- voting
    async def vote(self, rnd: int):
        window = self.session.cfg.vote_duration_sec
        await asyncio.sleep(random.uniform(2, max(3, window * 0.5)))   # don't vote instantly
        target = None
        if self.provider != "rule_based":
            try:
                prompt = (f"Voting time for round {rnd}.{self._feedback_note()}\nChat so far:\n"
                          f"{_transcript(self.session)}\n\nWho do you vote for as Decision Maker? "
                          f"Answer with exactly one letter from {', '.join(self.labels)}.")
                out = await self._llm(prompt, max_tokens=5)
                m = re.search(r"\b([A-C])\b", out.upper())
                target = m.group(1) if m and m.group(1) in self.labels else None
            except Exception as e:
                log.warning("LLM vote failed (%s), using rule-based vote", e)
        if target is None:
            self._update_favorite_from_chat(rnd)
            target = self.favorite
        await self.session.record_vote(self.label, target)

    # ------------------------------------------------------------ rule-based
    def _name(self, label: str) -> str:
        if label == self.label:
            return "me"
        return random.choice([label, f"player {label}"])

    def _feedback_note(self) -> str:
        if not self.session.tallies or not self.session.cfg.show_intermediate_results:
            return ""
        t = self.session.tallies[-1]
        return " Last round's votes: " + ", ".join(f"{k}={v}" for k, v in t.items()) + "."

    def _update_favorite_after_round(self, rnd: int):
        tally = self.session.tallies[rnd - 1]
        top = max(tally.values())
        leaders = [l for l, c in tally.items() if c == top]
        if top > 0 and len(leaders) == 1 and random.random() < 0.65:
            self.favorite = leaders[0]                  # mild conformity to the group

    def _update_favorite_from_chat(self, rnd: int):
        mentions = {l: 0 for l in self.labels}
        for m in self.session.messages:
            if m["round"] != rnd or m["from"] == self.label:
                continue
            for l in self.labels:
                if re.search(rf"\b{l.lower()}\b", m["text"].lower()):
                    mentions[l] += 1
        best = max(mentions, key=mentions.get)
        if mentions[best] >= 2 and random.random() < 0.5:
            self.favorite = best

    def _pick(self, options: list[str]) -> str:
        fresh = [o for o in options if o not in self.used] or options
        choice = random.choice(fresh)
        self.used.add(choice)
        return choice

    def _rule_based_message(self, rnd: int) -> str | None:
        fav = self._name(self.favorite)
        others_msgs = [m for m in self.session.messages if m["from"] != self.label]
        last = others_msgs[-1]["text"].lower() if others_msgs else ""

        if re.search(r"\b(bot|ai|robot|human|real person)\b", last):
            return self._pick(["haha let's just focus on picking someone",
                               "lol why, anyway who are we going with",
                               "not sure that matters, we need to pick someone"])
        if last and re.search(rf"\b(player\s*)?{self.label.lower()}\b", last):
            return self._pick(["sure, i could do it if you all agree",
                               "i'm fine either way honestly",
                               f"i'd be ok with it, but {self._name(random.choice([l for l in self.labels if l != self.label]))} works too"])
        if last.endswith("?"):
            return self._pick([f"no strong opinion, maybe {fav}?",
                               f"idk, {fav} seems fine to me",
                               "hard to say without knowing the task tbh"])

        if rnd == 1:
            if self.favorite == self.label:
                return self._pick(["hi, i don't mind being the decision maker if nobody else wants to",
                                   "hey all. i'm happy to volunteer for it",
                                   "i can do it, i'm usually ok making calls"])
            return self._pick([f"hi! i think {fav} could be a good pick",
                               f"hey, anyone want to volunteer? otherwise {fav}?",
                               f"i'd go with {fav} unless someone really wants it",
                               "what do you think the decision maker will have to do?"])
        return self._pick([f"i'd stick with {fav}",
                           f"ok so {fav} then?",
                           f"let's just go with {fav}, seems like the easiest",
                           "fine with whatever most people prefer"])

    # ------------------------------------------------------------------- LLM
    async def _llm(self, prompt: str, max_tokens: int) -> str:
        system = SYSTEM_PROMPT.format(me=self.label, players=", ".join(self.labels))
        async with httpx.AsyncClient(timeout=15) as client:
            if self.provider == "openai":
                r = await client.post(
                    "https://api.openai.com/v1/chat/completions",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json={"model": self.cfg.get("openai_model", "gpt-4o-mini"), "max_tokens": max_tokens,
                          "temperature": 0.9,
                          "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}]},
                )
                r.raise_for_status()
                return r.json()["choices"][0]["message"]["content"] or ""
            r = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={"x-api-key": self.api_key, "anthropic-version": "2023-06-01"},
                json={"model": self.cfg.get("anthropic_model", "claude-haiku-5-5"), "max_tokens": max_tokens,
                      "system": system, "messages": [{"role": "user", "content": prompt}]},
            )
            r.raise_for_status()
            return "".join(b.get("text", "") for b in r.json()["content"])
