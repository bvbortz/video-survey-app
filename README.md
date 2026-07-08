# video-survey-app

Tiny FastAPI app for a **human-preference (MOS) study** on AI-generated video quality.
A rater sees a pair of videos (same prompt, two conditions) and grades **each** on
five 0–10 categories mirroring the automatic evaluator. Companion design docs live in
the main repo under `user-survey/` (`PLAN.md`, `AZURE_DEPLOY_GUIDE.md`).

## Layout
```
app/
  main.py        FastAPI: /api/session, /api/response, /admin, static
  assignment.py  least-judged-first pair selection + A/B randomisation
  db.py          Mongo (motor) handle
  static/        one-page frontend (index.html, app.js, style.css)
scripts/
  load_pairs.py  import pairs.json (from export_survey_pairs.py) into Mongo
Dockerfile
```

## Data flow
1. `finetune-data-gen/export_survey_pairs.py` → `pairs.json` + `survey_videos/`.
2. Videos → Azure Blob (see deploy guide). `pairs.json` → Mongo via `load_pairs.py`.
3. App serves sessions; each `/api/session` hands out the least-judged pairs, hides
   leg identity, randomises A/B. `/api/response` stores the 2×5 scores resolved back
   to the true leg.

## Local dev
```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
export MONGO_URI='mongodb+srv://...'          # Atlas M0 or local mongod
export VIDEO_BASE_URL='https://acct.blob.core.windows.net/videos'
export ADMIN_SECRET='some-long-secret'
python scripts/load_pairs.py ../user-survey/pairs.json
uvicorn app.main:app --reload
# open http://localhost:8000
```

## Admin
Cookie-gated (no login form). In the browser console:
```js
document.cookie = "admin_token=<ADMIN_SECRET>;path=/";
```
then open `/admin` (coverage/counts) or `/admin/export` (full JSON dump).

## Tests
```bash
pip install pytest mongomock-motor httpx
pytest
```

## Deploy
See `user-survey/AZURE_DEPLOY_GUIDE.md` (GHCR image → Azure Container Apps, scale-to-zero).
