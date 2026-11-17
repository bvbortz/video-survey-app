"""FastAPI survey app.

The survey at / is one study at a time: two clips of one prompt side by side, the rater
picks the better one (app/survey.py). Each study is a set of pairs loaded under its own
study id (scripts/load_study.py); loading one retires the previous study's pairs, and every
answer carries the study it belongs to. The earlier MOS survey that lived here was removed
on 2026-11-17; its answers stay in Mongo (responses, sessions) and nothing here reads them.

Endpoints:
  GET  /api/health              liveness
  GET  /, /api/round, /api/answer   the current study (app/survey.py)
  GET  /admin, /admin/export        its counts and answers, cookie-gated
  GET  /check, /api/check/*     Ten Clip Check, pass/fail of single clips (app/check.py)
  GET  /compare, /api/compare/* Which Clip Is Better, judge-test pairs (app/compare.py)
  GET  /rate, /api/rate/*       Rate the Clips: one prompt's clips, pass/fail each and the best (app/rate.py)
"""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles

from . import db as dbmod
from .check import router as check_router
from .compare import router as compare_router
from .rate import router as rate_router
from .survey import router as survey_router

logger = logging.getLogger("survey")

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
app.include_router(survey_router)
app.include_router(check_router)
app.include_router(compare_router)
app.include_router(rate_router)


def _video_url(file: str) -> str:
    return f"{VIDEO_BASE_URL}/{file}" if VIDEO_BASE_URL else file


def _check_admin(request: Request) -> None:
    if not ADMIN_SECRET or request.cookies.get("admin_token") != ADMIN_SECRET:
        raise HTTPException(
            401,
            "admin cookie missing/invalid. In the browser console run: "
            "document.cookie = 'admin_token=<secret>;path=/' then reload.",
        )


@app.get("/api/health")
async def health():
    return {"ok": True}


# static last: / serves static/index.html, the study page
if STATIC_DIR.exists():
    app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")
