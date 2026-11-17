#!/usr/bin/env python3
"""Load a study's manifest (finetune-data-gen/ext_survey.py export -> user-survey/study_manifest.json)
into MongoDB for the survey at / (app/survey.py): study_clips and study_pairs.

The manifest names its study. Loading it upserts its clips and pairs and retires every pair of
any other study, so / serves this one only; answers to the old study stay, tagged with theirs.
Refuses a manifest whose pairs name clips it does not hold, a clip with no Hebrew or Russian
text, or a pair of another study.

Usage:
  export MONGO_URI='mongodb+srv://survey_app:...@.../survey'
  python scripts/load_study.py ../user-survey/study_manifest.json [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import os
import sys


def check(m: dict) -> list[str]:
    errs = []
    study = m.get("study")
    if not study:
        return ["manifest has no study id"]
    clips = {c["clip_id"]: c for c in m["clips"]}
    for c in m["clips"]:
        if not (c.get("prompt_text_he") and c.get("prompt_text_ru")):
            errs.append(f"clip {c['clip_id']}: no Hebrew or Russian text")
    for p in m["pairs"]:
        if not {"pair_id", "study", "a", "b", "prompt_key", "legs", "core"} <= set(p):
            errs.append(f"pair {p.get('pair_id')}: missing fields")
        elif p["study"] != study:
            errs.append(f"pair {p['pair_id']}: study {p['study']} in a {study} manifest")
        elif not {p["a"], p["b"]} <= set(clips) or set(p["legs"]) != {p["a"], p["b"]}:
            errs.append(f"pair {p['pair_id']}: clips not in the manifest")
    return errs


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("manifest")
    ap.add_argument("--db", default="survey")
    ap.add_argument("--dry-run", action="store_true", help="check the manifest only")
    args = ap.parse_args()
    m = json.load(open(args.manifest))
    errs = check(m)
    if errs:
        print(f"{len(errs)} problem(s), e.g. {errs[0]}", file=sys.stderr)
        return 2
    print(f"study {m['study']}: {len(m['pairs'])} pairs ({sum(p['core'] for p in m['pairs'])} core), "
          f"{len(m['clips'])} clips")
    if args.dry_run:
        return 0
    uri = os.environ.get("MONGO_URI")
    if not uri:
        print("set MONGO_URI", file=sys.stderr)
        return 2
    from pymongo import MongoClient, UpdateOne
    db = MongoClient(uri)[args.db]
    db.study_clips.create_index("clip_id", unique=True)
    db.study_pairs.create_index("pair_id", unique=True)
    r = db.study_clips.bulk_write([UpdateOne({"clip_id": c["clip_id"]}, {"$set": c}, upsert=True)
                                   for c in m["clips"]])
    print(f"study_clips: {r.upserted_count} new, {r.modified_count} updated")
    r = db.study_pairs.bulk_write([UpdateOne({"pair_id": p["pair_id"]}, {"$set": {**p, "active": True}}, upsert=True)
                                   for p in m["pairs"]])
    print(f"study_pairs: {r.upserted_count} new, {r.modified_count} updated")
    r = db.study_pairs.update_many({"study": {"$ne": m["study"]}, "active": {"$ne": False}}, {"$set": {"active": False}})
    print(f"retired {r.modified_count} pair(s) of other studies")
    return 0


if __name__ == "__main__":
    sys.exit(main())
