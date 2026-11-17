"""Mongo connection holder. Kept tiny so tests can inject a mock client."""
from __future__ import annotations

import os

from motor.motor_asyncio import AsyncIOMotorClient

_db = None


def init_db(uri: str | None = None, dbname: str = "survey"):
    """Connect using MONGO_URI (or the passed uri) and remember the handle."""
    global _db
    uri = uri or os.environ["MONGO_URI"]
    client = AsyncIOMotorClient(uri, uuidRepresentation="standard")
    _db = client[dbname]
    return _db


def set_db(db) -> None:
    """Test hook: point the app at an already-constructed (e.g. mock) db."""
    global _db
    _db = db


def get_db():
    if _db is None:
        raise RuntimeError("db not initialised; call init_db() first")
    return _db


async def ensure_indexes(db) -> None:
    # the survey at / (app/survey.py)
    await db.study_clips.create_index("clip_id", unique=True)
    await db.study_pairs.create_index("pair_id", unique=True)
    await db.study_pairs.create_index("study")
    await db.study_answers.create_index("pair_id")
    await db.study_answers.create_index("rater_id")
    await db.study_answers.create_index("study")
    # Ten Clip Check (app/check.py)
    await db.check_clips.create_index("clip_id", unique=True)
    await db.check_answers.create_index("clip_id")
    await db.check_answers.create_index("rater_id")
    # Rate the Clips (app/rate.py)
    await db.rate_prompts.create_index("prompt_key", unique=True)
    await db.rate_answers.create_index("prompt_key")
    await db.rate_answers.create_index("rater_id")
