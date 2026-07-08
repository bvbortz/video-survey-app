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
    await db.pairs.create_index("pair_id", unique=True)
    await db.pairs.create_index("is_attention_check")
    await db.pairs.create_index("arm")
    await db.clips.create_index("clip_id", unique=True)
    await db.responses.create_index("pair_id")
    await db.responses.create_index("session_id")
    await db.sessions.create_index("session_id", unique=True)
