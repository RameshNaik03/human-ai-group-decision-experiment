"""Load and validate config.yml."""
import os
from dataclasses import dataclass, field

import yaml

VALID_TYPES = {"human", "ai"}


@dataclass
class Config:
    condition: str
    participant_types: list[str]
    labels: list[str]
    rounds: int = 2
    round_duration_sec: int = 60
    vote_duration_sec: int = 30
    between_rounds_sec: int = 6
    waiting_timeout_sec: int = 300
    show_intermediate_results: bool = True
    shuffle_labels: bool = True
    matching_delay_sec: tuple[float, float] = (3, 8)
    ai: dict = field(default_factory=dict)

    @property
    def num_humans(self) -> int:
        return sum(1 for t in self.participant_types if t == "human")

    def public(self) -> dict:
        """Settings that are safe to show participants (no participant types!)."""
        return {
            "labels": self.labels,
            "rounds": self.rounds,
            "round_duration_sec": self.round_duration_sec,
            "vote_duration_sec": self.vote_duration_sec,
        }


def load_config(path: str | None = None) -> Config:
    path = path or os.getenv("CONFIG_PATH", "config.yml")
    with open(path) as f:
        raw = yaml.safe_load(f)

    condition = os.getenv("CONDITION") or raw["active_condition"]
    conditions = raw.get("conditions", {})
    if condition not in conditions:
        raise ValueError(f"Unknown condition '{condition}'. Options: {list(conditions)}")

    exp = raw.get("experiment", {})
    labels = exp.get("labels", ["A", "B", "C"])
    types = [str(t).lower() for t in conditions[condition]["participants"]]

    if len(types) != len(labels):
        raise ValueError(f"Condition '{condition}' has {len(types)} participants but {len(labels)} labels")
    if not set(types) <= VALID_TYPES:
        raise ValueError(f"Participant types must be one of {VALID_TYPES}, got {types}")
    if "human" not in types:
        raise ValueError("At least one participant must be human")

    return Config(
        condition=condition,
        participant_types=types,
        labels=labels,
        rounds=int(exp.get("rounds", 2)),
        round_duration_sec=int(exp.get("round_duration_sec", 60)),
        vote_duration_sec=int(exp.get("vote_duration_sec", 30)),
        between_rounds_sec=int(exp.get("between_rounds_sec", 6)),
        waiting_timeout_sec=int(exp.get("waiting_timeout_sec", 300)),
        show_intermediate_results=bool(exp.get("show_intermediate_results", True)),
        shuffle_labels=bool(exp.get("shuffle_labels", True)),
        matching_delay_sec=tuple(exp.get("matching_delay_sec", [3, 8])),
        ai=raw.get("ai", {}) or {},
    )
