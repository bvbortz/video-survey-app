#!/usr/bin/env python3
"""Fill the gaps in app/i18n_prompts_he.json for a survey manifest.

run_survey_refresh.sh refuses to load a manifest containing a prompt with no
Hebrew translation, because the Hebrew survey would render it blank. A new export
round therefore needs its new prompts translated first. This does that pass.

    export GEMINI_API_KEY=...
    python scripts/translate_missing_prompts.py ../user-survey/pairs.json
    python scripts/translate_missing_prompts.py ../user-survey/pairs.json --apply

Without --apply nothing is written: it reports what is missing and, if a key is
present, produces the translations into a review file so they can be read before
they reach a rater. THESE ARE MACHINE TRANSLATIONS — the prompt is the thing the
rater judges the video against, so a mistranslation silently corrupts a verdict.
Read review_he.tsv before applying.

Existing entries are never overwritten. The file is keyed on the exact English
string, matching push_hebrew_prompts.py.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
HE_JSON = HERE.parent / "app" / "i18n_prompts_he.json"

# Small batches: one bad line in a 200-item response costs the whole call, and the
# numbered round-trip below is only reliable while the model can hold the list.
BATCH = 20

SYSTEM = """You translate short English video-action prompts into Hebrew for a \
video-quality survey. These sentences describe what should happen in a short video \
clip; a rater reads the Hebrew and judges whether the video does it.

Rules:
- Translate meaning, not word order. Natural, plain modern Hebrew.
- Keep it one sentence, present tense, same level of detail. Do not add, remove or
  "improve" any detail — a colour, a count or a direction that changes is a
  corrupted survey item.
- Some prompts deliberately contain a detail that does not match the video's
  starting image. Translate it faithfully anyway. Do not correct it.
- Keep proper nouns and any embedded English technical words as they are.
- Return ONLY the numbered translations, one per line, in the form "N. <hebrew>",
  with exactly the same numbers you were given and nothing else."""


def translate(client, model: str, items: list[str]) -> list[str]:
    from google.genai import types
    numbered = "\n".join(f"{i + 1}. {t}" for i, t in enumerate(items))
    res = client.models.generate_content(
        model=model,
        contents=numbered,
        config=types.GenerateContentConfig(system_instruction=SYSTEM,
                                           temperature=0.0),
    )
    out: dict[int, str] = {}
    for line in (res.text or "").splitlines():
        line = line.strip()
        if not line or "." not in line:
            continue
        num, _, rest = line.partition(".")
        if num.strip().isdigit():
            out[int(num.strip())] = rest.strip()
    # Positional parsing only — never fall back to "whatever came back in order",
    # which is how a translation lands on the wrong prompt.
    missing = [i for i in range(1, len(items) + 1) if i not in out]
    if missing:
        raise RuntimeError(f"model returned no line for item(s) {missing}")
    return [out[i] for i in range(1, len(items) + 1)]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("manifest", type=Path, help="pairs.json from export_survey_pairs.py")
    ap.add_argument("--he-json", type=Path, default=HE_JSON)
    ap.add_argument("--model", default="gemini-2.5-pro")
    ap.add_argument("--review", type=Path, default=HERE.parent / "review_he.tsv")
    ap.add_argument("--apply", action="store_true",
                    help="write the new entries into --he-json")
    args = ap.parse_args()

    pairs = json.loads(args.manifest.read_text())["pairs"]
    wanted = sorted({p["prompt_text"] for p in pairs if p.get("prompt_text")})
    he = json.loads(args.he_json.read_text(encoding="utf-8"))
    missing = [t for t in wanted if t not in he]

    print(f"manifest prompts: {len(wanted)}")
    print(f"already translated: {len(wanted) - len(missing)}")
    print(f"missing: {len(missing)}")
    if not missing:
        print("nothing to do.")
        return 0

    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        print("\nGEMINI_API_KEY not set — reporting only.", file=sys.stderr)
        for t in missing[:10]:
            print("  -", t)
        return 1

    from google import genai
    client = genai.Client(api_key=key)

    done: dict[str, str] = {}
    for i in range(0, len(missing), BATCH):
        chunk = missing[i:i + BATCH]
        try:
            out = translate(client, args.model, chunk)
        except Exception as e:
            print(f"  batch {i // BATCH + 1} failed ({e}); skipping", file=sys.stderr)
            continue
        done.update(dict(zip(chunk, out)))
        print(f"  {len(done)}/{len(missing)}", flush=True)

    args.review.write_text(
        "\n".join(f"{en}\t{he_}" for en, he_ in done.items()), encoding="utf-8")
    print(f"\nreview file -> {args.review}  ({len(done)} rows)")

    if not args.apply:
        print("not written. Read the review file, then re-run with --apply.")
        return 0

    he.update(done)
    args.he_json.write_text(
        json.dumps(he, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
    print(f"wrote {args.he_json}  ({len(he)} entries)")
    still = [t for t in wanted if t not in he]
    if still:
        print(f"WARNING: {len(still)} prompt(s) still untranslated — "
              "run_survey_refresh.sh will refuse the load.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
