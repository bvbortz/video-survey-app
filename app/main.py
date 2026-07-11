"""FastAPI survey app — MOS video-rating study.

The rater sees a pair of videos (same prompt, two conditions) and grades EACH video
on the 6 evaluator categories, 0-10 (scene_fidelity added 2026-07-11; earlier
responses lack it — analysis imputes 10). See ../user-survey/PLAN.md for the design.

Endpoints:
  GET  /api/health              liveness
  GET  /api/session             new session + assigned items (A/B pre-randomised)
  POST /api/response            store the 2x6 scores for one item
  GET  /admin                   cookie-gated coverage dashboard
  GET  /admin/export            cookie-gated full response dump (JSON)
  GET  /                        static one-page frontend
"""
from __future__ import annotations

import os
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from . import db as dbmod
from .assignment import build_session_items, pair_token

RUBRIC = [
    "prompt_adherence", "scene_fidelity", "motion_quality", "object_consistency",
    "visual_quality", "physical_realism",
]

CONSENT_TEXT = (
    "This is an anonymous academic research survey on AI-generated video quality. "
    "You will watch pairs of short videos and rate each one on six aspects. "
    "It takes about 8-10 minutes. No personal data is collected (only an anonymous "
    "session id). Participation is voluntary and you may stop at any time. "
    "By pressing Start you consent to participate."
)

VIDEO_BASE_URL = os.environ.get("VIDEO_BASE_URL", "").rstrip("/")
ADMIN_SECRET = os.environ.get("ADMIN_SECRET", "")
STATIC_DIR = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Tests call dbmod.set_db() before startup and skip MONGO_URI.
    if os.environ.get("MONGO_URI"):
        db = dbmod.init_db()
        await dbmod.ensure_indexes(db)
    yield


app = FastAPI(title="video-survey-app", lifespan=lifespan)


def _now():
    return datetime.now(timezone.utc)


def _video_url(file: str) -> str:
    return f"{VIDEO_BASE_URL}/{file}" if VIDEO_BASE_URL else file


# ---------------------------------------------------------------- public API

@app.get("/api/health")
async def health():
    return {"ok": True}


@app.get("/api/session")
async def create_session(seen: str = ""):
    db = dbmod.get_db()
    # `seen` = comma-separated opaque pair tokens this browser has already rated
    seen_tokens = {s for s in seen.split(",") if s}
    items = await build_session_items(db, seen_tokens=seen_tokens)
    if not items:
        raise HTTPException(503, "no pairs loaded")

    session_id = str(uuid.uuid4())
    # what we persist (server-side truth for resolving A/B -> leg on submit)
    assignments = [
        {"index": i, "pair_id": it["pair_id"], "kind": it["kind"], "order": it["order"]}
        for i, it in enumerate(items)
    ]
    await db.sessions.insert_one({
        "session_id": session_id,
        "created_at": _now(),
        "assignments": assignments,
        "n_items": len(items),
    })

    # what the client sees — leg identity hidden, just URLs for slot A / slot B
    client_items = []
    for i, it in enumerate(items):
        legs = {leg["leg"]: leg for leg in it["pair"]["legs"]}
        a_leg, b_leg = it["order"][0], it["order"][1]
        client_items.append({
            "index": i,
            "token": pair_token(it["pair"]["pair_id"]),  # opaque, for cross-round dedup
            "prompt_text": it["pair"].get("prompt_text"),
            "image_url": _video_url(it["pair"]["image_file"]) if it["pair"].get("image_file") else None,
            "video_a": _video_url(legs[a_leg]["file"]),
            "video_b": _video_url(legs[b_leg]["file"]),
        })

    return {
        "session_id": session_id,
        "consent": CONSENT_TEXT,
        "rubric": RUBRIC,
        "items": client_items,
    }


class Scores(BaseModel):
    prompt_adherence: int
    # Added 2026-07-11; Optional so clients that loaded the page before the deploy
    # can still submit. Analysis treats a missing value as 10 (perfect fidelity).
    scene_fidelity: Optional[int] = None
    motion_quality: int
    object_consistency: int
    visual_quality: int
    physical_realism: int

    @field_validator("*")
    @classmethod
    def in_range(cls, v: Optional[int]) -> Optional[int]:
        if v is not None and not (0 <= v <= 10):
            raise ValueError("score must be 0-10")
        return v


class ResponseIn(BaseModel):
    session_id: str
    index: int = Field(ge=0)
    video_a: Scores
    video_b: Scores
    elapsed_ms: int = Field(ge=0)
    # rater flags a problem with this pair (impossible/mismatched prompt, NSFW, other);
    # `note` describes what's wrong
    flag_issue: bool = False
    note: str = Field(default="", max_length=1000)


@app.post("/api/response")
async def submit_response(body: ResponseIn):
    db = dbmod.get_db()
    session = await db.sessions.find_one({"session_id": body.session_id})
    if not session:
        raise HTTPException(404, "unknown session")
    assignment = next(
        (a for a in session["assignments"] if a["index"] == body.index), None
    )
    if assignment is None:
        raise HTTPException(400, "bad item index")

    a_leg, b_leg = assignment["order"][0], assignment["order"][1]
    # de-dupe: one submission per (session, index)
    await db.responses.update_one(
        {"session_id": body.session_id, "index": body.index},
        {"$set": {
            "session_id": body.session_id,
            "index": body.index,
            "pair_id": assignment["pair_id"],
            "kind": assignment["kind"],
            "created_at": _now(),
            "elapsed_ms": body.elapsed_ms,
            "ratings": {                       # stored resolved to leg identity
                # exclude_none: a pre-2026-07-11 cached client may omit scene_fidelity;
                # analysis treats the absent key as 10.
                a_leg: body.video_a.model_dump(exclude_none=True),
                b_leg: body.video_b.model_dump(exclude_none=True),
            },
            "flag_issue": body.flag_issue,
            "note": body.note.strip(),
        }},
        upsert=True,
    )
    return {"ok": True}


# ---------------------------------------------------------------- admin

def _check_admin(request: Request) -> None:
    if not ADMIN_SECRET or request.cookies.get("admin_token") != ADMIN_SECRET:
        raise HTTPException(
            401,
            "admin cookie missing/invalid. In the browser console run: "
            "document.cookie = 'admin_token=<secret>;path=/' then reload.",
        )


@app.get("/admin")
async def admin(request: Request):
    _check_admin(request)
    db = dbmod.get_db()
    total_sessions = await db.sessions.count_documents({})
    total_responses = await db.responses.count_documents({})
    total_pairs = await db.pairs.count_documents({"is_attention_check": {"$ne": True}})
    flagged = await db.responses.count_documents({"flag_issue": True})

    per_arm = {}
    cur = db.responses.aggregate([
        {"$lookup": {"from": "pairs", "localField": "pair_id",
                     "foreignField": "pair_id", "as": "p"}},
        {"$unwind": "$p"},
        {"$group": {"_id": {"arm": "$p.arm", "gen": "$p.generator"}, "n": {"$sum": 1}}},
    ])
    async for row in cur:
        per_arm[f"{row['_id']['gen']}/{row['_id']['arm']}"] = row["n"]

    judged = await db.responses.distinct("pair_id", {"kind": "real"})
    coverage = f"{len(judged)}/{total_pairs} real pairs judged at least once"

    return {
        "sessions": total_sessions,
        "responses": total_responses,
        "coverage": coverage,
        "flagged_issue": flagged,
        "responses_per_arm": per_arm,
    }


@app.get("/admin/export")
async def admin_export(request: Request):
    _check_admin(request)
    db = dbmod.get_db()
    docs = [d async for d in db.responses.find({}, {"_id": 0})]
    return JSONResponse(docs)


# ---------------------------------------------------------------- static (last)

if STATIC_DIR.exists():
    app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")
