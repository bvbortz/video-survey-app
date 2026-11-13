"""Rate the Clips — one prompt at a time: its clips side by side, pass / fail / not sure for each,
then the best of them: one clip, two that tie (2026-11-13; before that a single clip), or all
about the same.

One screen gives both kinds of label on the same clips: a pass/fail verdict per clip, and the
order inside the prompt (the best pick, plus the pass/fail split). The clips, pictures and Blob
files are the Ten Clip Check's (check_clips); a prompt's clip group is a rate_prompts row loaded
by scripts/load_rate_prompts.py (manifest from the main repo's
finetune-data-gen/export_check_clips.py --judgetest). Each round is N_ROUND prompts this rater
has not answered, lowest tier first (tier 0 = the core every rater gets), then fewest answers,
ties at random. The clip order on screen is random per showing and recorded.

Endpoints:
  GET  /rate                    the page (static/rate.html)
  GET  /api/rate/round          N_ROUND prompts for this rater (lang=ru: only prompts with a Russian text)
  POST /api/rate/answer         one prompt's answer; (rater_id, prompt_key) is the de-dupe key
  GET  /admin/rate              cookie-gated counts
  GET  /admin/rate/export       cookie-gated full answer dump (JSON)
"""
from __future__ import annotations

import logging
import random
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from . import db as dbmod

logger = logging.getLogger("survey.rate")
router = APIRouter()

N_ROUND = 5
VERDICTS = ("pass", "fail", "unsure")
SAME = "same"
ACTIVE = {"active": {"$ne": False}}
PAGE = Path(__file__).parent / "static" / "rate.html"


def _video_url(file: str) -> str:
    from .main import _video_url as url   # one VIDEO_BASE_URL rule for all studies
    return url(file)


@router.get("/rate")
async def rate_page():
    return FileResponse(PAGE)


def pick_round(prompts: list[dict], counts: dict[str, int], seen: set[str], rng: random.Random,
               n: int = N_ROUND) -> list[dict]:
    """n prompts this rater has not answered: lowest tier first, then fewest answers, ties at random."""
    left = [p for p in prompts if p["prompt_key"] not in seen]
    rng.shuffle(left)
    left.sort(key=lambda p: (p.get("tier", 0), counts.get(p["prompt_key"], 0)))
    return left[:n]


@router.get("/api/rate/round")
async def rate_round(rater: str = "", seen: str = "", lang: str = "en"):
    db = dbmod.get_db()
    rater_id = rater.strip()[:64] or None
    done = {s for s in seen.split(",") if s}   # this browser's memory, plus the server's
    if rater_id:
        done |= set(await db.rate_answers.distinct("prompt_key", {"rater_id": rater_id}))
    clips = {c["clip_id"]: c async for c in db.check_clips.find(ACTIVE, {"_id": 0})}
    # a prompt is live only while all of its clips are
    prompts = [p async for p in db.rate_prompts.find(ACTIVE, {"_id": 0}) if all(c in clips for c in p["clips"])]
    if lang == "ru":   # Russian raters get only prompts that have a Russian text
        prompts = [p for p in prompts if clips[p["clips"][0]].get("prompt_text_ru")]
    if not prompts:
        raise HTTPException(503, "no prompts loaded")
    counts = {}
    async for row in db.rate_answers.aggregate([{"$group": {"_id": "$prompt_key", "n": {"$sum": 1}}}]):
        counts[row["_id"]] = row["n"]
    rng = random.Random()
    items = []
    for p in pick_round(prompts, counts, done, rng):
        order = list(p["clips"])
        rng.shuffle(order)
        c = clips[order[0]]
        items.append({"prompt_key": p["prompt_key"], "prompt_text": c["prompt_text"],
                      "prompt_text_he": c.get("prompt_text_he"), "prompt_text_ru": c.get("prompt_text_ru"),
                      "image_url": _video_url(c["image_file"]),
                      "clips": [{"clip_id": k, "url": _video_url(clips[k]["file"])} for k in order]})
    return {"left": sum(p["prompt_key"] not in done for p in prompts) - len(items), "items": items}


class AnswerIn(BaseModel):
    prompt_key: str = Field(max_length=64)
    order: list[str] = Field(max_length=8)           # clip ids as shown, left to right
    verdicts: dict[str, str]                          # clip id -> pass / fail / unsure
    best: str | None = Field(default=None, max_length=64)   # pages before 2026-11-13: a clip id, or "same"
    best_set: list[str] | None = Field(default=None, max_length=8)   # clip ids (one, or tied), or ["same"]
    note: str = Field(default="", max_length=1000)
    prompt_flag: bool = False                         # the rater finds the text itself strange or impossible
    elapsed_ms: int = Field(ge=0)
    round: int = Field(default=1, ge=1)
    lang: str = Field(default="en", max_length=8)
    rater_id: str | None = Field(default=None, max_length=64)


async def _persist(db, doc: dict) -> None:
    """After the rater has moved on (see main._persist_response): log loudly on failure."""
    try:
        if doc["rater_id"]:
            await db.rate_answers.update_one(
                {"rater_id": doc["rater_id"], "prompt_key": doc["prompt_key"]}, {"$set": doc}, upsert=True)
        else:   # anonymous (storage blocked): nothing to de-dupe on
            await db.rate_answers.insert_one(doc)
    except Exception:
        logger.exception("LOST RATE ANSWER rater=%s prompt=%s", doc.get("rater_id"), doc.get("prompt_key"))


@router.post("/api/rate/answer")
async def rate_answer(body: AnswerIn, background: BackgroundTasks):
    db = dbmod.get_db()
    p = await db.rate_prompts.find_one({"prompt_key": body.prompt_key}, {"_id": 0, "clips": 1})
    if not p or sorted(body.order) != sorted(p["clips"]):
        raise HTTPException(400, "unknown prompt or clips")
    if set(body.verdicts) != set(p["clips"]) or not all(v in VERDICTS for v in body.verdicts.values()):
        raise HTTPException(400, "a pass / fail / not sure answer is needed for every clip")
    raw = body.best_set if body.best_set is not None else ([body.best] if body.best else [])
    picked = [] if raw == [SAME] else raw
    if not raw or len(set(picked)) != len(picked) or not set(picked) <= set(p["clips"]):
        raise HTTPException(400, "best must be clips of this prompt, or 'same'")
    if len(picked) == len(p["clips"]):   # every clip picked: all about the same
        picked = []
    # best_set: the clips picked as best ([] = all about the same); best: the one clip when only one was
    doc = {"rater_id": body.rater_id or None, "prompt_key": body.prompt_key, "order": body.order,
           "verdicts": body.verdicts, "best_set": sorted(picked), "best": picked[0] if len(picked) == 1 else None,
           "note": body.note.strip(), "prompt_flag": body.prompt_flag, "elapsed_ms": body.elapsed_ms,
           "round": body.round, "lang": body.lang, "created_at": datetime.now(timezone.utc)}
    background.add_task(_persist, db, doc)
    return {"ok": True}


@router.get("/admin/rate")
async def rate_admin(request: Request):
    from .main import _check_admin
    _check_admin(request)
    db = dbmod.get_db()
    return {"prompts": await db.rate_prompts.count_documents(ACTIVE),
            "answers": await db.rate_answers.count_documents({}),
            "raters": len(await db.rate_answers.distinct("rater_id"))}


@router.get("/admin/rate/export")
async def rate_export(request: Request):
    from .main import _check_admin
    _check_admin(request)
    db = dbmod.get_db()
    docs = [d async for d in db.rate_answers.find({}, {"_id": 0})]
    for d in docs:
        d["created_at"] = d["created_at"].isoformat() if hasattr(d.get("created_at"), "isoformat") else d.get("created_at")
    return JSONResponse(docs)
