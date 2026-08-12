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

import logging
import os
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator, model_validator

from . import db as dbmod
from .assignment import ACTIVE, build_session_items, pair_token

logger = logging.getLogger("survey")

RUBRIC = [
    "prompt_adherence", "scene_fidelity", "motion_quality", "object_consistency",
    "visual_quality", "physical_realism",
]

# Forced-choice pairs (mode == "2afc") collect this instead of the rubric. Used for
# base_vs_finetuned, the comparison every other arm can only reach indirectly: rating
# two clips 0-10 and subtracting carries more noise (between-rater sd 0.90, within-rater
# 1.12) than the ~0.3 MOS effect being looked for.
#
# Pairs loaded before this existed have no `mode` field, so absent == "mos" — the same
# convention `active` uses. A pair only becomes forced-choice by saying so.
DEFAULT_MODE = "mos"
CHOICE_QUESTION = {
    "prompt": "Which video better matches the description, and looks more realistic?",
    "options": [
        {"value": "A", "label": "Video A is clearly better"},
        {"value": "B", "label": "Video B is clearly better"},
        {"value": "tie", "label": "About the same"},
    ],
}

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
    # `mode` is persisted with the assignment so submit can reject a payload of the
    # wrong shape without re-reading the pair, and so a pair whose mode is changed
    # mid-session cannot invalidate answers already given under the old one.
    assignments = [
        {"index": i, "pair_id": it["pair_id"], "kind": it["kind"], "order": it["order"],
         "mode": it["pair"].get("mode", DEFAULT_MODE)}
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
            "prompt_text_he": it["pair"].get("prompt_text_he"),  # None until push script runs
            "image_url": _video_url(it["pair"]["image_file"]) if it["pair"].get("image_file") else None,
            "video_a": _video_url(legs[a_leg]["file"]),
            "video_b": _video_url(legs[b_leg]["file"]),
            "mode": it["pair"].get("mode", DEFAULT_MODE),
        })

    return {
        "session_id": session_id,
        "consent": CONSENT_TEXT,
        "rubric": RUBRIC,
        "choice_question": CHOICE_QUESTION,
        "items": client_items,
    }


# All fields Optional: a FLAGGED pair may be submitted with partial (or no)
# ratings — a missing key means "not rated", never a default. Completeness for
# unflagged pairs is enforced in ResponseIn.full_scores_unless_flagged.
# (scene_fidelity added 2026-07-11 and additionally exempt for pre-deploy clients;
# analysis imputes 10 for it on UNFLAGGED responses only.)
class Scores(BaseModel):
    prompt_adherence: Optional[int] = None
    scene_fidelity: Optional[int] = None
    motion_quality: Optional[int] = None
    object_consistency: Optional[int] = None
    visual_quality: Optional[int] = None
    physical_realism: Optional[int] = None

    @field_validator("*")
    @classmethod
    def in_range(cls, v: Optional[int]) -> Optional[int]:
        if v is not None and not (0 <= v <= 10):
            raise ValueError("score must be 0-10")
        return v


class ResponseIn(BaseModel):
    session_id: str
    index: int = Field(ge=0)
    video_a: Scores = Field(default_factory=Scores)
    video_b: Scores = Field(default_factory=Scores)
    # Forced-choice answer for mode == "2afc" pairs. "A"/"B" are display positions;
    # submit_response resolves them to the leg before storing, because the position
    # is meaningless once the session's randomisation is gone.
    choice: Optional[str] = None
    elapsed_ms: int = Field(ge=0)
    # rater flags a problem with this pair (impossible/mismatched prompt, NSFW, other);
    # `note` describes what's wrong
    flag_issue: bool = False
    note: str = Field(default="", max_length=1000)

    # Unflagged responses must be complete (scene_fidelity exempt: pre-2026-07-11
    # cached clients don't have that slider). Flagged responses may be partial.
    @field_validator("choice")
    @classmethod
    def known_choice(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in {"A", "B", "tie"}:
            raise ValueError("choice must be A, B or tie")
        return v

    @model_validator(mode="after")
    def full_scores_unless_flagged(self):
        # A forced-choice submission carries no rubric scores, so the completeness
        # rule below does not apply to it. Whether this pair was actually served as
        # forced choice is checked in submit_response, which knows the assignment.
        if self.choice is not None:
            return self
        if not self.flag_issue:
            required = [d for d in RUBRIC if d != "scene_fidelity"]
            for label, scores in (("video_a", self.video_a), ("video_b", self.video_b)):
                missing = [d for d in required if getattr(scores, d) is None]
                if missing:
                    raise ValueError(
                        f"{label} is missing scores {missing}; "
                        "only flagged pairs may be submitted with partial ratings"
                    )
        return self


async def _persist_response(db, doc: dict) -> None:
    """Write the rating after the rater has already moved on. Nobody is waiting on
    this, so a failure is silent to them — log it loudly, it is unrecoverable data."""
    try:
        await db.responses.update_one(
            {"session_id": doc["session_id"], "index": doc["index"]},
            {"$set": doc}, upsert=True)
    except Exception:
        logger.exception("LOST RATING session=%s index=%s pair=%s",
                         doc.get("session_id"), doc.get("index"), doc.get("pair_id"))


@app.post("/api/response")
async def submit_response(body: ResponseIn, background: BackgroundTasks):
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
    mode = assignment.get("mode", DEFAULT_MODE)

    # Reject a payload of the wrong shape rather than storing a response that looks
    # like the other kind. A 2afc pair answered with sliders, or a mos pair answered
    # with a choice, means the client and the server disagree about what was shown.
    if mode == "2afc" and body.choice is None and not body.flag_issue:
        raise HTTPException(400, "this pair was served as a forced choice; `choice` required")
    if mode != "2afc" and body.choice is not None:
        raise HTTPException(400, "this pair was served for rating; `choice` not accepted")

    # de-dupe key is (session, index), so the upsert is idempotent and a client
    # retry after a timeout cannot double-count.
    doc = {
        "session_id": body.session_id,
        "index": body.index,
        "pair_id": assignment["pair_id"],
        "kind": assignment["kind"],
        "mode": mode,
        "created_at": _now(),
        "elapsed_ms": body.elapsed_ms,
        "flag_issue": body.flag_issue,
        "note": body.note.strip(),
    }
    if mode == "2afc":
        # Stored as the leg, never as the display letter: "A" is meaningless once this
        # session's randomisation is gone, and every analysis joins on leg identity.
        doc["choice_leg"] = (
            None if body.choice is None else
            "tie" if body.choice == "tie" else
            (a_leg if body.choice == "A" else b_leg)
        )
        doc["shown_as"] = body.choice
    else:
        doc["ratings"] = {                 # stored resolved to leg identity
            # exclude_none: a pre-2026-07-11 cached client may omit scene_fidelity;
            # analysis treats the absent key as 10.
            a_leg: body.video_a.model_dump(exclude_none=True),
            b_leg: body.video_b.model_dump(exclude_none=True),
        }
    # Validation and leg resolution have already happened, so the rater gets their
    # answer now and the write lands after. Atlas is a free tier in another region
    # and a write can take tens of seconds; making someone sit through that once per
    # pair is the difference between finishing the survey and abandoning it.
    background.add_task(_persist_response, db, doc)
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
    total_pairs = await db.pairs.count_documents(
        {"is_attention_check": {"$ne": True}, **ACTIVE})
    retired_pairs = await db.pairs.count_documents({"active": False})
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
    coverage = (f"{len(judged)}/{total_pairs} real pairs judged at least once"
                + (f" ({retired_pairs} retired)" if retired_pairs else ""))

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


# ------------------------------------------------- admin: browse pairs / shortlist
# A gallery for picking the clips that go on the GitHub page. Ranked by the human
# rating gap between the two legs, because "best" here means the improvement is
# visible to a person — not that the automatic score is high. Those scores carry
# roughly +/-0.08 of run-to-run noise and cannot order clips this finely.

def _leg_means(rating_docs: list[dict]) -> dict[str, dict]:
    """pair_id -> {leg: mean over metrics and raters, 'n': raters}."""
    acc: dict[str, dict[str, list[float]]] = {}
    counts: dict[str, int] = {}
    for r in rating_docs:
        pid = r.get("pair_id")
        if not pid:
            continue
        counts[pid] = counts.get(pid, 0) + 1
        for leg, scores in (r.get("ratings") or {}).items():
            vals = [v for v in (scores or {}).values() if isinstance(v, (int, float))]
            if vals:
                acc.setdefault(pid, {}).setdefault(leg, []).extend(vals)
    out = {}
    for pid, legs in acc.items():
        out[pid] = {leg: sum(v) / len(v) for leg, v in legs.items()}
        out[pid]["n"] = counts.get(pid, 0)
    return out


@app.get("/admin/pairs.json")
async def admin_pairs_data(request: Request, version: str = "", arm: str = "",
                           starred: int = 0, limit: int = 400):
    _check_admin(request)
    db = dbmod.get_db()

    q: dict = {"is_attention_check": {"$ne": True}, **ACTIVE}
    if version:
        q["version"] = version
    if arm:
        q["arm"] = arm
    pairs = [p async for p in db.pairs.find(q, {"_id": 0})]

    # Only the two fields the aggregation needs, and only for the pairs on screen.
    # Atlas is on a free tier in another region, so a full response scan is felt.
    pair_ids = [p["pair_id"] for p in pairs]
    human = _leg_means([r async for r in db.responses.find(
        {"pair_id": {"$in": pair_ids}}, {"_id": 0, "pair_id": 1, "ratings": 1})])
    stars = {s["pair_id"] async for s in db.shortlist.find({"starred": True}, {"_id": 0})}

    rows = []
    for p in pairs:
        legs = p.get("legs", [])
        if len(legs) != 2:
            continue
        h = human.get(p["pair_id"], {})
        ref, other = legs[0], legs[1]          # legs[0] is always the "short" reference
        hr, ho = h.get(ref["leg"]), h.get(other["leg"])
        gap = (ho - hr) if isinstance(hr, float) and isinstance(ho, float) else None
        auto = [l.get("auto_score") for l in legs]
        auto_gap = (auto[1] - auto[0]) if all(isinstance(a, (int, float)) for a in auto) else None
        rows.append({
            "pair_id": p["pair_id"], "arm": p.get("arm"), "version": p.get("version"),
            "generator": p.get("generator"), "prompt_text": p.get("prompt_text"),
            "phrasing": p.get("phrasing"),
            "starred": p["pair_id"] in stars,
            "n_ratings": h.get("n", 0),
            "human_gap": gap, "auto_gap": auto_gap,
            "legs": [{"leg": l["leg"], "url": _video_url(l["file"]),
                      "auto_score": l.get("auto_score"),
                      "human": h.get(l["leg"])} for l in legs],
        })

    if starred:
        rows = [r for r in rows if r["starred"]]
    # Rated pairs first, ordered by how much better the second leg looked to people;
    # unrated pairs fall back to the automatic gap so the page is still usable on a
    # freshly loaded set with no responses yet.
    rows.sort(key=lambda r: (r["human_gap"] is None,
                             -(r["human_gap"] if r["human_gap"] is not None
                               else (r["auto_gap"] or 0))))
    return JSONResponse({"count": len(rows), "rows": rows[:limit],
                         "versions": sorted({p.get("version") for p in pairs if p.get("version")})})


@app.post("/admin/pairs/{pair_id}/star")
async def admin_star(pair_id: str, request: Request):
    _check_admin(request)
    db = dbmod.get_db()
    cur = await db.shortlist.find_one({"pair_id": pair_id})
    new = not (cur or {}).get("starred", False)
    await db.shortlist.update_one({"pair_id": pair_id},
                                  {"$set": {"starred": new, "updated_at": _now()}},
                                  upsert=True)
    return {"pair_id": pair_id, "starred": new}


@app.get("/admin/pairs")
async def admin_pairs_page(request: Request):
    _check_admin(request)
    page = Path(__file__).parent / "templates" / "admin_pairs.html"
    return HTMLResponse(page.read_text(encoding="utf-8"))


# ---------------------------------------------------------------- static (last)

if STATIC_DIR.exists():
    app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")
