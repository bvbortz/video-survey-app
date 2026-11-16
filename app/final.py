"""Final survey — the extender against zero-shot Qwen on the campaign's test prompts.

Each pair is one test prompt: the clip from zero-shot Qwen's expansion (leg "base") and the
clip from the trained extender's (leg "ext"), rendered the same way. The rater sees the
first frame, the short prompt, the two clips side by side in random order, and answers
A better / about the same / B better: the /compare page (static/compare.js) on its own
collections, so nothing here mixes with the judge-test studies.

A round is N_ROUND pairs, one per prompt, none this rater has answered: first up to N_CORE
from the fixed core (every rater meets the same core pairs, so raters can be compared),
fewest answers first; the rest from the other pairs, fewest answers first, ties at random.
Nothing about the clips' content or any judge score decides what is served.

The leg of each clip stays on the server; an answer stores better_leg ("base" | "ext" |
None for about the same) and src, the ?src= tag of the link the rater came in by (the
first, small group's link and the wide one carry different tags).

Pairs and clips are loaded by scripts/load_final.py (manifest from the main repo's
finetune-data-gen/final_survey.py export).

Endpoints:
  GET  /final                 the page (static/final.html)
  GET  /api/final/round       N_ROUND pairs for this rater
  POST /api/final/answer      one choice; (rater_id, pair_id) is the de-dupe key
  GET  /admin/final           cookie-gated counts
  GET  /admin/final/export    cookie-gated full answer dump (JSON)
"""
from __future__ import annotations

import logging
import random
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import Field

from . import db as dbmod
from .compare import AnswerIn

logger = logging.getLogger("survey.final")
router = APIRouter()

N_ROUND = 8
N_CORE = 2
ACTIVE = {"active": {"$ne": False}}
PAGE = Path(__file__).parent / "static" / "final.html"


def _video_url(file: str) -> str:
    from .main import _video_url as url   # one VIDEO_BASE_URL rule for all studies
    return url(file)


@router.get("/final")
async def final_page():
    return FileResponse(PAGE)


def pick_round(pairs: list[dict], counts: dict[str, int], seen: set[str], rng: random.Random,
               n: int = N_ROUND, n_core: int = N_CORE) -> list[dict]:
    """Up to n_core unseen core pairs, then unseen others; fewest answers first, ties at random;
    one pair per prompt."""
    left = [p for p in pairs if p["pair_id"] not in seen]
    rng.shuffle(left)
    left.sort(key=lambda p: counts.get(p["pair_id"], 0))
    out, used = [], set()
    for want_core, cap in ((True, n_core), (False, n)):
        for p in left:
            if len(out) >= cap or len(out) >= n:
                break
            if bool(p.get("core")) == want_core and p["prompt_key"] not in used:
                used.add(p["prompt_key"])
                out.append(p)
    if len(out) < n:   # this rater has had every non-core pair: fill with core ones
        for p in left:
            if len(out) == n:
                break
            if p["prompt_key"] not in used:
                used.add(p["prompt_key"])
                out.append(p)
    return out


@router.get("/api/final/round")
async def final_round(rater: str = "", seen: str = "", lang: str = "en"):
    db = dbmod.get_db()
    rater_id = rater.strip()[:64] or None
    done = {s for s in seen.split(",") if s}   # this browser's memory, plus the server's
    if rater_id:
        done |= set(await db.final_answers.distinct("pair_id", {"rater_id": rater_id}))
    clips = {c["clip_id"]: c async for c in db.final_clips.find(ACTIVE, {"_id": 0})}
    pairs = [p async for p in db.final_pairs.find(ACTIVE, {"_id": 0}) if p["a"] in clips and p["b"] in clips]
    if lang == "ru":
        pairs = [p for p in pairs if clips[p["a"]].get("prompt_text_ru")]
    if not pairs:
        raise HTTPException(503, "no pairs loaded")
    counts = {}
    async for row in db.final_answers.aggregate([{"$group": {"_id": "$pair_id", "n": {"$sum": 1}}}]):
        counts[row["_id"]] = row["n"]
    rng = random.Random()
    pick = pick_round(pairs, counts, done, rng)
    items = []
    for p in pick:
        first, second = (p["a"], p["b"]) if rng.random() < 0.5 else (p["b"], p["a"])
        c = clips[first]
        items.append({"pair_id": p["pair_id"], "prompt_text": c["prompt_text"],
                      "prompt_text_he": c.get("prompt_text_he"), "prompt_text_ru": c.get("prompt_text_ru"),
                      "image_url": _video_url(c["image_file"]),
                      "first": first, "second": second,
                      "first_url": _video_url(c["file"]), "second_url": _video_url(clips[second]["file"])})
    return {"left": sum(p["pair_id"] not in done for p in pairs) - len(pick), "items": items}


class FinalAnswerIn(AnswerIn):
    src: str = Field(default="", max_length=32)


async def _persist(db, doc: dict) -> None:
    """After the rater has moved on (see main._persist_response): log loudly on failure."""
    try:
        if doc["rater_id"]:
            await db.final_answers.update_one(
                {"rater_id": doc["rater_id"], "pair_id": doc["pair_id"]}, {"$set": doc}, upsert=True)
        else:   # anonymous (storage blocked): nothing to de-dupe on
            await db.final_answers.insert_one(doc)
    except Exception:
        logger.exception("LOST FINAL ANSWER rater=%s pair=%s", doc.get("rater_id"), doc.get("pair_id"))


@router.post("/api/final/answer")
async def final_answer(body: FinalAnswerIn, background: BackgroundTasks):
    db = dbmod.get_db()
    p = await db.final_pairs.find_one({"pair_id": body.pair_id}, {"_id": 0, "a": 1, "b": 1, "legs": 1})
    if not p or {body.first, body.second} != {p["a"], p["b"]}:
        raise HTTPException(400, "unknown pair")
    better = {"first": body.first, "second": body.second}.get(body.choice)   # None = about the same
    doc = {"rater_id": body.rater_id or None, "pair_id": body.pair_id, "first": body.first,
           "second": body.second, "choice": body.choice, "better": better,
           "better_leg": p["legs"][better] if better else None, "first_leg": p["legs"][body.first],
           "note": body.note.strip(), "prompt_flag": body.prompt_flag, "elapsed_ms": body.elapsed_ms,
           "round": body.round, "lang": body.lang, "src": body.src.strip(),
           "created_at": datetime.now(timezone.utc)}
    background.add_task(_persist, db, doc)
    return {"ok": True}


@router.get("/admin/final")
async def final_admin(request: Request):
    from .main import _check_admin
    _check_admin(request)
    db = dbmod.get_db()
    return {"pairs": await db.final_pairs.count_documents(ACTIVE),
            "answers": await db.final_answers.count_documents({}),
            "raters": len(await db.final_answers.distinct("rater_id"))}


@router.get("/admin/final/export")
async def final_export(request: Request):
    from .main import _check_admin
    _check_admin(request)
    db = dbmod.get_db()
    docs = [d async for d in db.final_answers.find({}, {"_id": 0})]
    for d in docs:
        d["created_at"] = d["created_at"].isoformat() if hasattr(d.get("created_at"), "isoformat") else d.get("created_at")
    return JSONResponse(docs)
