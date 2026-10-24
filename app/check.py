"""Ten Clip Check — single-clip pass/fail rounds for agreement between people.

A separate study from the MOS survey, sharing its app, Mongo and Blob. Each round is 10
clips, one per prompt, least-answered first, none this rater has answered before. The
pool is loaded by scripts/load_check_clips.py (manifest from the main repo's
finetune-data-gen/export_check_clips.py). Design: JUDGE_RESET_PLAN.md, "Ten Clip Check".

Endpoints:
  GET  /check                   the page (static/check.html)
  GET  /api/check/round         10 clips for this rater
  POST /api/check/answer        one verdict; (rater_id, clip_id) is the de-dupe key
  GET  /admin/check             cookie-gated counts
  GET  /admin/check/export      cookie-gated full answer dump (JSON)
"""
from __future__ import annotations

import logging
import random
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field, field_validator

from . import db as dbmod

logger = logging.getLogger("survey.check")
router = APIRouter()

N_ROUND = 10
VERDICTS = ("pass", "fail", "unsure")
ACTIVE = {"active": {"$ne": False}}
PAGE = Path(__file__).parent / "static" / "check.html"


def _now():
    return datetime.now(timezone.utc)


def _video_url(file: str) -> str:
    from .main import _video_url as url   # one VIDEO_BASE_URL rule for both studies
    return url(file)


@router.get("/check")
async def check_page():
    return FileResponse(PAGE)


def pick_round(clips: list[dict], counts: dict[str, int], seen: set[str], rng: random.Random,
               n: int = N_ROUND) -> list[dict]:
    """n unseen clips, one per prompt, fewest answers first, ties at random."""
    left = [c for c in clips if c["clip_id"] not in seen]
    rng.shuffle(left)
    left.sort(key=lambda c: counts.get(c["clip_id"], 0))
    out, used = [], set()
    for c in left:
        if len(out) == n:
            break
        if c["prompt_key"] not in used:
            used.add(c["prompt_key"])
            out.append(c)
    return out


@router.get("/api/check/round")
async def check_round(rater: str = "", seen: str = ""):
    db = dbmod.get_db()
    rater_id = rater.strip()[:64] or None
    # what this browser remembers, plus what the server has from this rater id: either
    # alone can be missing (storage cleared, or blocked so there is no stable id)
    done = {s for s in seen.split(",") if s}
    if rater_id:
        done |= set(await db.check_answers.distinct("clip_id", {"rater_id": rater_id}))
    clips = [c async for c in db.check_clips.find(ACTIVE, {"_id": 0})]
    if not clips:
        raise HTTPException(503, "no check clips loaded")
    counts = {}
    async for row in db.check_answers.aggregate([{"$group": {"_id": "$clip_id", "n": {"$sum": 1}}}]):
        counts[row["_id"]] = row["n"]
    pick = pick_round(clips, counts, done, random.Random())
    return {
        "left": sum(c["clip_id"] not in done for c in clips) - len(pick),
        "items": [{"clip_id": c["clip_id"], "prompt_text": c["prompt_text"],
                   "prompt_text_he": c.get("prompt_text_he"),
                   "image_url": _video_url(c["image_file"]), "video_url": _video_url(c["file"])}
                  for c in pick],
    }


class AnswerIn(BaseModel):
    clip_id: str = Field(max_length=64)
    verdict: str
    note: str = Field(default="", max_length=1000)
    elapsed_ms: int = Field(ge=0)
    round: int = Field(default=1, ge=1)
    lang: str = Field(default="en", max_length=8)
    rater_id: str | None = Field(default=None, max_length=64)

    @field_validator("verdict")
    @classmethod
    def known(cls, v: str) -> str:
        if v not in VERDICTS:
            raise ValueError("verdict must be pass, fail or unsure")
        return v


async def _persist(db, doc: dict) -> None:
    """After the rater has moved on (see main._persist_response): log loudly on failure."""
    try:
        if doc["rater_id"]:
            await db.check_answers.update_one(
                {"rater_id": doc["rater_id"], "clip_id": doc["clip_id"]}, {"$set": doc}, upsert=True)
        else:   # anonymous (storage blocked): nothing to de-dupe on
            await db.check_answers.insert_one(doc)
    except Exception:
        logger.exception("LOST CHECK ANSWER rater=%s clip=%s", doc.get("rater_id"), doc.get("clip_id"))


@router.post("/api/check/answer")
async def check_answer(body: AnswerIn, background: BackgroundTasks):
    db = dbmod.get_db()
    if not await db.check_clips.find_one({"clip_id": body.clip_id}, {"_id": 1}):
        raise HTTPException(400, "unknown clip")
    doc = {"rater_id": body.rater_id or None, "clip_id": body.clip_id, "verdict": body.verdict,
           "note": body.note.strip(), "elapsed_ms": body.elapsed_ms, "round": body.round,
           "lang": body.lang, "created_at": _now()}
    background.add_task(_persist, db, doc)
    return {"ok": True}


@router.get("/admin/check")
async def check_admin(request: Request):
    from .main import _check_admin
    _check_admin(request)
    db = dbmod.get_db()
    return {"clips": await db.check_clips.count_documents(ACTIVE),
            "answers": await db.check_answers.count_documents({}),
            "raters": len(await db.check_answers.distinct("rater_id"))}


@router.get("/admin/check/export")
async def check_export(request: Request):
    from .main import _check_admin
    _check_admin(request)
    db = dbmod.get_db()
    docs = [d async for d in db.check_answers.find({}, {"_id": 0})]
    for d in docs:
        d["created_at"] = d["created_at"].isoformat() if hasattr(d.get("created_at"), "isoformat") else d.get("created_at")
    return JSONResponse(docs)
