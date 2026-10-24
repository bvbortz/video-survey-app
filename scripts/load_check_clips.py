#!/usr/bin/env python3
"""Load check_clips.json (from finetune-data-gen/export_check_clips.py) into MongoDB.

Idempotent: upserts by clip_id. --retire-others sets active=False on clips not in this
manifest (their answers stay joinable).

Usage:
  export MONGO_URI='mongodb+srv://survey_app:...@.../survey'
  python scripts/load_check_clips.py ../user-survey/check_clips.json
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
    clips = json.load(open(args.manifest))["clips"]
    need = {"clip_id", "prompt_key", "prompt_text", "file", "image_file"}
    bad = [c.get("clip_id") for c in clips if not need <= set(c)]
    if bad:
        print(f"manifest rows missing fields: {bad[:5]}", file=sys.stderr)
        return 2
    db = MongoClient(uri)[args.db]
    db.check_clips.create_index("clip_id", unique=True)
    res = db.check_clips.bulk_write([UpdateOne({"clip_id": c["clip_id"]}, {"$set": {**c, "active": True}}, upsert=True)
                                     for c in clips])
    print(f"check_clips: {res.upserted_count} new, {res.modified_count} updated, {len(clips)} in manifest")
    if args.retire_others:
        r = db.check_clips.update_many({"clip_id": {"$nin": [c["clip_id"] for c in clips]}}, {"$set": {"active": False}})
        print(f"retired {r.modified_count}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
