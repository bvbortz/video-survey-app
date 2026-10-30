"""Which Clip Is Better — two clips of the same prompt side by side, pick the better one.

The pairwise companion of the Ten Clip Check (app/check.py), on the same clips, Mongo
and Blob files. A pass/fail answer depends on where each person draws the line; one
person comparing two clips of the same prompt does not. Each round is 10 pairs, one per
prompt, none this rater has answered, prompts and clips they have not seen first. Among
those, pairs rater 1 separated (tier 1) are served first until each has TARGET answers,
then the rest, fewest answers first. Which clip is shown
as A is random per showing and recorded. Pairs are loaded by scripts/load_check_pairs.py
(manifest from the main repo's finetune-data-gen/export_check_pairs.py).

Endpoints:
  GET  /compare                 the page (static/compare.html)
  GET  /api/compare/round       10 pairs for this rater
  POST /api/compare/answer      one choice; (rater_id, pair_id) is the de-dupe key
  GET  /admin/compare           cookie-gated counts
  GET  /admin/compare/export    cookie-gated full answer dump (JSON)
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

logger = logging.getLogger("survey.compare")
router = APIRouter()

N_ROUND = 10
TARGET = 5          # answers per tier-1 pair before tier 2 is served
CHOICES = ("first", "second", "same")
ACTIVE = {"active": {"$ne": False}}
PAGE = Path(__file__).parent / "static" / "compare.html"


def _video_url(file: str) -> str:
    from .main import _video_url as url   # one VIDEO_BASE_URL rule for all studies
    return url(file)


@router.get("/compare")
async def compare_page():
    return FileResponse(PAGE)


def pick_round(pairs: list[dict], counts: dict[str, int], seen: set[str], rng: random.Random,
               n: int = N_ROUND) -> list[dict]:
    """n unseen pairs, one per prompt. A prompt this rater has not had comes first, then a
    pair with fewer clips they have already watched (a new pair of familiar clips feels
    like a repeat); then tier-1 pairs short of TARGET, then by tier, then fewest answers,
    ties at random."""
    had = [p for p in pairs if p["pair_id"] in seen]
    old_prompts = {p["prompt_key"] for p in had}
    old_clips = {c for p in had for c in (p["a"], p["b"])}
    left = [p for p in pairs if p["pair_id"] not in seen]
    rng.shuffle(left)
    left.sort(key=lambda p: (p["prompt_key"] in old_prompts, (p["a"] in old_clips) + (p["b"] in old_clips),
                             counts.get(p["pair_id"], 0) >= TARGET, p["tier"], counts.get(p["pair_id"], 0)))
    out, used = [], set()
    for p in left:
        if len(out) == n:
            break
        if p["prompt_key"] not in used:
            used.add(p["prompt_key"])
            out.append(p)
    return out


@router.get("/api/compare/round")
async def compare_round(rater: str = "", seen: str = ""):
    db = dbmod.get_db()
    rater_id = rater.strip()[:64] or None
    done = {s for s in seen.split(",") if s}   # this browser's memory, plus the server's
    if rater_id:
        done |= set(await db.compare_answers.distinct("pair_id", {"rater_id": rater_id}))
    clips = {c["clip_id"]: c async for c in db.check_clips.find(ACTIVE, {"_id": 0})}
    # a pair is live only while both of its clips are
    pairs = [p async for p in db.check_pairs.find(ACTIVE, {"_id": 0}) if p["a"] in clips and p["b"] in clips]
    if not pairs:
        raise HTTPException(503, "no pairs loaded")
    counts = {}
    async for row in db.compare_answers.aggregate([{"$group": {"_id": "$pair_id", "n": {"$sum": 1}}}]):
        counts[row["_id"]] = row["n"]
    rng = random.Random()
    pick = pick_round(pairs, counts, done, rng)
    items = []
    for p in pick:
        first, second = (p["a"], p["b"]) if rng.random() < 0.5 else (p["b"], p["a"])
        c = clips[first]
        items.append({"pair_id": p["pair_id"], "prompt_text": c["prompt_text"],
                      "prompt_text_he": c.get("prompt_text_he"), "image_url": _video_url(c["image_file"]),
                      "first": first, "second": second,
                      "first_url": _video_url(c["file"]), "second_url": _video_url(clips[second]["file"])})
    return {"left": sum(p["pair_id"] not in done for p in pairs) - len(pick), "items": items}


class AnswerIn(BaseModel):
    pair_id: str = Field(max_length=200)
    first: str = Field(max_length=64)
    second: str = Field(max_length=64)
    choice: str
    note: str = Field(default="", max_length=1000)
    prompt_flag: bool = False      # the rater finds the text itself strange or impossible
    elapsed_ms: int = Field(ge=0)
    round: int = Field(default=1, ge=1)
    lang: str = Field(default="en", max_length=8)
    rater_id: str | None = Field(default=None, max_length=64)

    @field_validator("choice")
    @classmethod
    def known(cls, v: str) -> str:
        if v not in CHOICES:
            raise ValueError("choice must be first, second or same")
        return v


async def _persist(db, doc: dict) -> None:
    """After the rater has moved on (see main._persist_response): log loudly on failure."""
    try:
        if doc["rater_id"]:
            await db.compare_answers.update_one(
                {"rater_id": doc["rater_id"], "pair_id": doc["pair_id"]}, {"$set": doc}, upsert=True)
        else:   # anonymous (storage blocked): nothing to de-dupe on
            await db.compare_answers.insert_one(doc)
    except Exception:
        logger.exception("LOST COMPARE ANSWER rater=%s pair=%s", doc.get("rater_id"), doc.get("pair_id"))


@router.post("/api/compare/answer")
async def compare_answer(body: AnswerIn, background: BackgroundTasks):
    db = dbmod.get_db()
    p = await db.check_pairs.find_one({"pair_id": body.pair_id}, {"_id": 0, "a": 1, "b": 1})
    if not p or {body.first, body.second} != {p["a"], p["b"]}:
        raise HTTPException(400, "unknown pair")
    better = {"first": body.first, "second": body.second}.get(body.choice)   # None = about the same
    doc = {"rater_id": body.rater_id or None, "pair_id": body.pair_id, "first": body.first,
           "second": body.second, "choice": body.choice, "better": better, "note": body.note.strip(),
           "prompt_flag": body.prompt_flag, "elapsed_ms": body.elapsed_ms, "round": body.round, "lang": body.lang,
           "created_at": datetime.now(timezone.utc)}
    background.add_task(_persist, db, doc)
    return {"ok": True}


@router.get("/admin/compare")
async def compare_admin(request: Request):
    from .main import _check_admin
    _check_admin(request)
    db = dbmod.get_db()
    return {"pairs": await db.check_pairs.count_documents(ACTIVE),
            "answers": await db.compare_answers.count_documents({}),
            "raters": len(await db.compare_answers.distinct("rater_id"))}


@router.get("/admin/compare/export")
async def compare_export(request: Request):
    from .main import _check_admin
    _check_admin(request)
    db = dbmod.get_db()
    docs = [d async for d in db.compare_answers.find({}, {"_id": 0})]
    for d in docs:
        d["created_at"] = d["created_at"].isoformat() if hasattr(d.get("created_at"), "isoformat") else d.get("created_at")
    return JSONResponse(docs)
