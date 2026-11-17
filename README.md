# video-survey-app

Tiny FastAPI app for human judgements of AI-generated video. The survey at `/` runs one
**study** at a time: two clips of the same prompt side by side, the rater picks the better
one (or about the same), 8 pairs a round, English / Hebrew / Russian. Each study is loaded
under its own id; loading one retires the previous study's pairs, and every answer carries
its study, so studies never mix. `/check`, `/compare` and `/rate` are the judge-test pages.

## Layout
```
app/
  main.py        FastAPI app, health, admin cookie check, static mount
  survey.py      the study at /: /api/round, /api/answer, /admin, /admin/export
  check.py, compare.py, rate.py   the judge-test pages
  db.py          Mongo (motor) handle and indexes
  static/        index.html (the study) and the other pages; compare.js drives both side-by-side pages
scripts/
  load_study.py  import a study manifest (finetune-data-gen/ext_survey.py export) into Mongo
Dockerfile
```

## Data flow
1. `finetune-data-gen/ext_survey.py export` -> `user-survey/study_manifest.json` + `user-survey/study_videos/`.
2. `user-survey/run_study_upload.sh` puts the clips on Azure Blob under `study/`;
   `scripts/load_study.py` loads the manifest into Mongo (`study_clips`, `study_pairs`).
3. `/api/round` hands each rater the core pairs first, then the least-answered, hides which
   clip is which leg and randomises sides; `/api/answer` stores the choice resolved to the leg
   (`study_answers`).

## Local dev
```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
export MONGO_URI='mongodb+srv://...'          # Atlas M0 or local mongod
export VIDEO_BASE_URL='https://acct.blob.core.windows.net/videos'
export ADMIN_SECRET='some-long-secret'
python scripts/load_study.py ../user-survey/study_manifest.json
uvicorn app.main:app --reload
# open http://localhost:8000
```

## Admin
Cookie-gated (no login form). In the browser console:
```js
document.cookie = "admin_token=<ADMIN_SECRET>;path=/";
```
then open `/admin` (answers per study) or `/admin/export?study=<id>` (that study's answers as JSON).

## Tests
```bash
pip install pytest mongomock-motor httpx
pytest
```

## Deploy
See `user-survey/AZURE_DEPLOY_GUIDE.md` (GHCR image → Azure Container Apps, scale-to-zero).
