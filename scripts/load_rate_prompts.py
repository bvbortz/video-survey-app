#!/usr/bin/env python3
"""Load rate_prompts_*.json (from finetune-data-gen/export_check_clips.py --judgetest) into MongoDB:
one row per prompt, its clip ids and tier (0 = the core every rater gets first), for app/rate.py.
The clips themselves go in check_clips first (scripts/load_check_clips.py on the same export's
clip manifest; they carry rate_only, so /check does not serve them one at a time).

Idempotent: upserts by prompt_key. --retire-others sets active=False on prompts not in this
manifest (their answers stay joinable).

Usage:
  export MONGO_URI='mongodb+srv://survey_app:...@.../survey'
  python scripts/load_rate_prompts.py ../user-survey/rate_prompts_judgetest.json [--retire-others]
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from pymongo import MongoClient, UpdateOne


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("manifest")
    ap.add_argument("--db", default="survey")
    ap.add_argument("--retire-others", action="store_true")
    args = ap.parse_args()
    uri = os.environ.get("MONGO_URI")
    if not uri:
        print("set MONGO_URI", file=sys.stderr)
        return 2
    prompts = json.load(open(args.manifest))["prompts"]
    need = {"prompt_key", "clips", "tier"}
    bad = [p.get("prompt_key") for p in prompts if not need <= set(p) or len(p["clips"]) < 2]
    if bad:
        print(f"manifest rows missing fields or clips: {bad[:5]}", file=sys.stderr)
        return 2
    db = MongoClient(uri)[args.db]
    clips = set(db.check_clips.distinct("clip_id", {"active": {"$ne": False}}))
    orphan = [p["prompt_key"] for p in prompts if not set(p["clips"]) <= clips]
    if orphan:
        print(f"{len(orphan)} prompts name clips that are not active in check_clips, e.g. {orphan[0]};"
              " run load_check_clips.py first", file=sys.stderr)
        return 2
    db.rate_prompts.create_index("prompt_key", unique=True)
    res = db.rate_prompts.bulk_write([UpdateOne({"prompt_key": p["prompt_key"]}, {"$set": {**p, "active": True}},
                                                upsert=True) for p in prompts])
    print(f"rate_prompts: {res.upserted_count} new, {res.modified_count} updated, {len(prompts)} in manifest")
    if args.retire_others:
        r = db.rate_prompts.update_many({"prompt_key": {"$nin": [p["prompt_key"] for p in prompts]}},
                                        {"$set": {"active": False}})
        print(f"retired {r.modified_count}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
