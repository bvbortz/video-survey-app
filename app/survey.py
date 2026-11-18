"""The survey at / — one study at a time: two clips of one prompt side by side, which is better.

A study is a set of pairs loaded under one study id by scripts/load_study.py (manifest from
the main repo's finetune-data-gen/ext_survey.py); loading a study retires every pair of the
others, so / always serves exactly one. Each pair is one prompt's two clips, each clip tagged
with its leg (e.g. "base" = zero-shot Qwen's expansion, "ext" = the trained extender's). The
legs stay on the server: the page gets clip ids and URLs, in random order, and the rater
answers A better / about the same / B better (static/compare.js, the /compare page's script).

A round is N_ROUND pairs, one per prompt, none this rater has answered: first up to N_CORE
from the study's fixed core (every rater meets the same core pairs, so raters can be
compared), fewest answers first; then the other pairs, fewest answers first, ties at random.
Nothing about the clips' content or any judge score decides what is served.

An answer stores its study, better_leg ("base" | "ext" | None for about the same) and src,
the ?src= tag of the link the rater came in by. Since 2026-11-18 (rater 1: an added question,
the study continues) the page also asks pass / fail / not sure for each clip before the choice;
the answer stores them by leg (verdict_leg = {"base": ..., "ext": ...}). Answers from before
carry no verdicts.

Endpoints:
  GET  /api/round       N_ROUND pairs for this rater
  POST /api/answer      one choice; (rater_id, pair_id) is the de-dupe key
  GET  /admin           cookie-gated counts per study
  GET  /admin/export    cookie-gated answer dump (JSON); ?study= limits it to one study
"""
from __future__ import annotations

import logging
import random
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import Field, field_validator

from . import db as dbmod
from .compare import AnswerIn

logger = logging.getLogger("survey.study")
router = APIRouter()

N_ROUND = 8
N_CORE = 2
ACTIVE = {"active": {"$ne": False}}


def _video_url(file: str) -> str:
    from .main import _video_url as url   # one VIDEO_BASE_URL rule for all studies
    return url(file)


def pick_round(pairs: list[dict], counts: dict[str, int], seen: set[str], rng: random.Random,
               n: int = N_ROUND, n_core: int = N_CORE) -> list[dict]:
    """Up to n_core unseen core pairs, then unseen others; fewest answers first, ties at random;
    one pair per prompt. A rater who has had every non-core pair gets the rest of the core."""
    left = [p for p in pairs if p["pair_id"] not in seen]
    rng.shuffle(left)
    left.sort(key=lambda p: counts.get(p["pair_id"], 0))
    out, used = [], set()
    for want_core, cap in ((True, n_core), (False, n), (None, n)):
        for p in left:
            if len(out) >= cap:
                break
            if (want_core is None or bool(p.get("core")) == want_core) and p["prompt_key"] not in used:
                used.add(p["prompt_key"])
                out.append(p)
    return out


@router.get("/api/round")
async def study_round(rater: str = "", seen: str = "", lang: str = "en"):
    db = dbmod.get_db()
    rater_id = rater.strip()[:64] or None
    done = {s for s in seen.split(",") if s}   # this browser's memory, plus the server's
    if rater_id:
        done |= set(await db.study_answers.distinct("pair_id", {"rater_id": rater_id}))
    pairs = [p async for p in db.study_pairs.find(ACTIVE, {"_id": 0})]
    clips = {c["clip_id"]: c async for c in db.study_clips.find(
        {"clip_id": {"$in": [c for p in pairs for c in (p["a"], p["b"])]}}, {"_id": 0})}
    pairs = [p for p in pairs if p["a"] in clips and p["b"] in clips]
    if lang == "ru":
        pairs = [p for p in pairs if clips[p["a"]].get("prompt_text_ru")]
    if not pairs:
        raise HTTPException(503, "no pairs loaded")
    counts = {}
    async for row in db.study_answers.aggregate([{"$group": {"_id": "$pair_id", "n": {"$sum": 1}}}]):
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


VERDICTS = {"pass", "fail", "unsure"}


class StudyAnswerIn(AnswerIn):
    src: str = Field(default="", max_length=32)
    verdict_first: str | None = None    # pass / fail / unsure for the first clip; None = not asked
    verdict_second: str | None = None

    @field_validator("verdict_first", "verdict_second")
    @classmethod
    def known_verdict(cls, v: str | None) -> str | None:
        if v is not None and v not in VERDICTS:
            raise ValueError("verdict must be pass, fail or unsure")
        return v


async def _persist(db, doc: dict) -> None:
    """After the rater has moved on: log loudly on failure."""
    try:
        if doc["rater_id"]:
            await db.study_answers.update_one(
                {"rater_id": doc["rater_id"], "pair_id": doc["pair_id"]}, {"$set": doc}, upsert=True)
        else:   # anonymous (storage blocked): nothing to de-dupe on
            await db.study_answers.insert_one(doc)
    except Exception:
        logger.exception("LOST STUDY ANSWER rater=%s pair=%s", doc.get("rater_id"), doc.get("pair_id"))


@router.post("/api/answer")
async def study_answer(body: StudyAnswerIn, background: BackgroundTasks):
    db = dbmod.get_db()
    p = await db.study_pairs.find_one({"pair_id": body.pair_id}, {"_id": 0, "a": 1, "b": 1, "legs": 1, "study": 1})
    if not p or {body.first, body.second} != {p["a"], p["b"]}:
        raise HTTPException(400, "unknown pair")
    better = {"first": body.first, "second": body.second}.get(body.choice)   # None = about the same
    doc = {"study": p["study"], "rater_id": body.rater_id or None, "pair_id": body.pair_id,
           "first": body.first, "second": body.second, "choice": body.choice, "better": better,
           "better_leg": p["legs"][better] if better else None, "first_leg": p["legs"][body.first],
           "note": body.note.strip(), "prompt_flag": body.prompt_flag, "elapsed_ms": body.elapsed_ms,
           "round": body.round, "lang": body.lang, "src": body.src.strip(),
           "created_at": datetime.now(timezone.utc)}
    if body.verdict_first or body.verdict_second:
        doc["verdicts"] = {body.first: body.verdict_first, body.second: body.verdict_second}
        doc["verdict_leg"] = {p["legs"][body.first]: body.verdict_first, p["legs"][body.second]: body.verdict_second}
    background.add_task(_persist, db, doc)
    return {"ok": True}


@router.get("/admin")
async def study_admin(request: Request):
    from .main import _check_admin
    _check_admin(request)
    db = dbmod.get_db()
    out = {}
    async for row in db.study_answers.aggregate([{"$group": {"_id": "$study", "answers": {"$sum": 1},
                                                             "raters": {"$addToSet": "$rater_id"}}}]):
        out[row["_id"]] = {"answers": row["answers"], "raters": len(row["raters"])}
    live = await db.study_pairs.distinct("study", ACTIVE)
    return {"live": live, "pairs_live": await db.study_pairs.count_documents(ACTIVE), "studies": out}


@router.get("/admin/export")
async def study_export(request: Request, study: str = ""):
    from .main import _check_admin
    _check_admin(request)
    db = dbmod.get_db()
    docs = [d async for d in db.study_answers.find({"study": study} if study else {}, {"_id": 0})]
    for d in docs:
        d["created_at"] = d["created_at"].isoformat() if hasattr(d.get("created_at"), "isoformat") else d.get("created_at")
    return JSONResponse(docs)
