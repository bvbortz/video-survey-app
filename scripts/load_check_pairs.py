#!/usr/bin/env python3
"""Load check_pairs.json (from finetune-data-gen/export_check_pairs.py) into MongoDB for
Which Clip Is Better (app/compare.py). The clips themselves come from load_check_clips.py.

Idempotent: upserts by pair_id. --retire-others sets active=False on pairs not in this
manifest (their answers stay joinable).

Usage:
  export MONGO_URI='mongodb+srv://survey_app:...@.../survey'
  python scripts/load_check_pairs.py ../user-survey/check_pairs.json [--retire-others]
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
    pairs = json.load(open(args.manifest))["pairs"]
    need = {"pair_id", "a", "b", "prompt_key", "tier"}
    bad = [p.get("pair_id") for p in pairs if not need <= set(p)]
    if bad:
        print(f"manifest rows missing fields: {bad[:5]}", file=sys.stderr)
        return 2
    db = MongoClient(uri)[args.db]
    clips = set(db.check_clips.distinct("clip_id", {"active": {"$ne": False}}))
    orphan = [p["pair_id"] for p in pairs if not {p["a"], p["b"]} <= clips]
    if orphan:
        print(f"{len(orphan)} pairs name clips that are not active in check_clips, e.g. {orphan[0]};"
              " run load_check_clips.py first", file=sys.stderr)
        return 2
    db.check_pairs.create_index("pair_id", unique=True)
    res = db.check_pairs.bulk_write([UpdateOne({"pair_id": p["pair_id"]}, {"$set": {**p, "active": True}}, upsert=True)
                                     for p in pairs])
    print(f"check_pairs: {res.upserted_count} new, {res.modified_count} updated, {len(pairs)} in manifest")
    if args.retire_others:
        r = db.check_pairs.update_many({"pair_id": {"$nin": [p["pair_id"] for p in pairs]}}, {"$set": {"active": False}})
        print(f"retired {r.modified_count}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
