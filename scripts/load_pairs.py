#!/usr/bin/env python3
"""Load pairs.json (from export_survey_pairs.py) into MongoDB.

Idempotent: upserts by pair_id / clip_id, so re-running after a new export (e.g.
FramePack legs added, or a retrain) just adds/updates rows.

Usage:
  export MONGO_URI='mongodb+srv://survey_app:...@.../survey'
  python scripts/load_pairs.py ../user-survey/pairs.json
  python scripts/load_pairs.py pairs.json --drop   # wipe collections first
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from pymongo import MongoClient, UpdateOne


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("manifest", help="path to pairs.json")
    ap.add_argument("--db", default="survey")
    ap.add_argument("--drop", action="store_true", help="drop pairs/clips first")
    args = ap.parse_args()

    uri = os.environ.get("MONGO_URI")
    if not uri:
        print("set MONGO_URI", file=sys.stderr)
        return 2

    with open(args.manifest) as f:
        manifest = json.load(f)
    pairs = manifest["pairs"]
    clips = manifest.get("clips", [])

    db = MongoClient(uri)[args.db]
    if args.drop:
        db.pairs.drop()
        db.clips.drop()

    db.pairs.create_index("pair_id", unique=True)
    db.clips.create_index("clip_id", unique=True)

    if pairs:
        db.pairs.bulk_write(
            [UpdateOne({"pair_id": p["pair_id"]}, {"$set": p}, upsert=True) for p in pairs]
        )
    if clips:
        db.clips.bulk_write(
            [UpdateOne({"clip_id": c["clip_id"]}, {"$set": c}, upsert=True) for c in clips]
        )

    print(f"loaded {len(pairs)} pairs, {len(clips)} clips into '{args.db}'")
    print("  attention-check pairs:",
          db.pairs.count_documents({"is_attention_check": True}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
