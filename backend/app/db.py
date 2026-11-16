"""Postgres persistence (SQLAlchemy async). Used for logging experiment data only;
live game state is kept in memory. All writes are best-effort so a DB hiccup
never breaks a running session."""
import asyncio
import logging
import os
from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, Integer, String, Text, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

log = logging.getLogger("db")

DATABASE_URL = os.getenv("DATABASE_URL")
engine = create_async_engine(DATABASE_URL, pool_pre_ping=True) if DATABASE_URL else None
SessionLocal = async_sessionmaker(engine, expire_on_commit=False) if engine else None


def now():
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class SessionRow(Base):
    __tablename__ = "sessions"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    condition: Mapped[str] = mapped_column(String(64))
    participants: Mapped[dict] = mapped_column(JSON)          # {"A": "human", "B": "ai", ...}
    config: Mapped[dict] = mapped_column(JSON)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    winner: Mapped[str | None] = mapped_column(String(8), nullable=True)
    decision_method: Mapped[str | None] = mapped_column(String(64), nullable=True)
    round_tallies: Mapped[list | None] = mapped_column(JSON, nullable=True)


class MessageRow(Base):
    __tablename__ = "messages"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String(32), index=True)
    round: Mapped[int] = mapped_column(Integer)
    sender: Mapped[str] = mapped_column(String(8))
    text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class VoteRow(Base):
    __tablename__ = "votes"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String(32), index=True)
    round: Mapped[int] = mapped_column(Integer)
    voter: Mapped[str] = mapped_column(String(8))
    target: Mapped[str] = mapped_column(String(8))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


async def init():
    if not engine:
        log.warning("DATABASE_URL not set - running without persistence")
        return
    for attempt in range(30):
        try:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            log.info("Database ready")
            return
        except Exception as e:  # db container may still be starting
            log.info("Waiting for database (%s): %s", attempt + 1, e)
            await asyncio.sleep(2)
    log.error("Database unavailable - continuing without persistence")


async def _add(row):
    if not SessionLocal:
        return
    try:
        async with SessionLocal() as s:
            s.add(row)
            await s.commit()
    except Exception:
        log.exception("DB write failed")


async def save_session_start(session_id, condition, participants, config):
    await _add(SessionRow(id=session_id, condition=condition, participants=participants, config=config))


async def save_message(session_id, rnd, sender, text):
    await _add(MessageRow(session_id=session_id, round=rnd, sender=sender, text=text))


async def save_vote(session_id, rnd, voter, target):
    await _add(VoteRow(session_id=session_id, round=rnd, voter=voter, target=target))


async def save_result(session_id, winner, method, tallies):
    if not SessionLocal:
        return
    try:
        async with SessionLocal() as s:
            await s.execute(
                update(SessionRow)
                .where(SessionRow.id == session_id)
                .values(ended_at=now(), winner=winner, decision_method=method, round_tallies=tallies)
            )
            await s.commit()
    except Exception:
        log.exception("DB write failed")
