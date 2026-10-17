"""
Run the pipeline evals and print a report.

    cd src
    python -m evals.run_eval                          # keyword baseline, no API key needed
    python -m evals.run_eval --predictor llm-pipeline # the real pipeline path (needs an LLM key)
    python -m evals.run_eval --predictor llm-model    # the model alone, every review, no selection gate
    python -m evals.run_eval --save preds.json        # keep predictions so they can be re-scored offline
    python -m evals.run_eval --predictions preds.json # re-score saved predictions, no key needed

The modifier eval and the source-selection ceiling are offline and always run.
"""

import argparse
import json
import os
from typing import Dict, List

from loguru import logger

from evals.baseline import keyword_baseline
from evals.metrics import (
    CaseKey,
    load_json,
    load_recipe_json,
    score_edit_grounding,
    score_extraction,
    score_modifier,
    score_source_selection,
    check_golden_integrity,
)
from llm_pipeline.models import ModificationObject

Predictions = Dict[CaseKey, List[ModificationObject]]


def baseline_predictions(golden) -> Predictions:
    preds: Predictions = {}
    for c in golden["cases"]:
        text = load_recipe_json(c["recipe_id"])["reviews"][c["review_index"]]["text"]
        preds[(c["recipe_id"], c["review_index"])] = keyword_baseline(text)
    return preds


def llm_predictions(golden, mode: str) -> Predictions:
    """Needs an LLM API key (OPENAI_API_KEY, GROQ_API_KEY or GEMINI_API_KEY)."""
    from llm_pipeline.models import Review
    from llm_pipeline.pipeline import LLMAnalysisPipeline
    from llm_pipeline.tweak_extractor import TweakExtractor

    helper = object.__new__(LLMAnalysisPipeline)  # parsing helpers use no instance state
    extractor = TweakExtractor()
    preds: Predictions = {(c["recipe_id"], c["review_index"]): [] for c in golden["cases"]}

    for rid in sorted({c["recipe_id"] for c in golden["cases"]}):
        data = load_recipe_json(rid)
        recipe = helper.parse_recipe_data(data)
        reviews = helper.parse_reviews_data(data)
        wanted = {c["review_index"] for c in golden["cases"] if c["recipe_id"] == rid}

        if mode == "llm-model":
            for idx in sorted(wanted):
                preds[(rid, idx)] = extractor.extract_modifications(reviews[idx], recipe)
        else:  # llm-pipeline: exactly what process_single_recipe does
            pairs = extractor.extract_modifications_from_reviews(helper.select_source_reviews(data), recipe)
            for mod, review in pairs:
                idx = next((i for i, r in enumerate(reviews) if r.text == review.text), None)
                if idx in wanted:
                    preds[(rid, idx)].append(mod)
    return preds


def save_predictions(path: str, preds: Predictions) -> None:
    out = {f"{rid}:{idx}": [m.model_dump() for m in mods] for (rid, idx), mods in preds.items()}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=1)


def load_predictions(path: str) -> Predictions:
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)
    return {
        (k.split(":")[0], int(k.split(":")[1])): [ModificationObject(**m) for m in mods] for k, mods in raw.items()
    }


def pct(x: float) -> str:
    return f"{x * 100:5.1f}%"


def print_report(name: str, golden, preds: Predictions, show_grounding: bool) -> None:
    logger.disable("llm_pipeline")  # the modifier warns on every deliberately bad edit in the golden set
    try:
        sel = score_source_selection(golden)
        ext = score_extraction(golden, preds)
        ground = score_edit_grounding(preds)
        mod = score_modifier(load_json("golden_modifier.json")["cases"])
    finally:
        logger.enable("llm_pipeline")

    print(f"\n=== Pipeline eval ({name}) ===")
    print(f"golden set: {len(golden['cases'])} reviews, {sel['tweaks_total']} scored tweaks")

    print("\n1. Source selection (offline): do the tweaks even reach the LLM?")
    print(f"   recall ceiling      {pct(sel['tweak_recall_ceiling'])}  ({sel['tweaks_lost_before_llm']} of {sel['tweaks_total']} tweaks never reach the model)")
    for lost in sel["lost_reviews"]:
        print(f"   lost: {lost['recipe_id']}[{lost['review_index']}] x{lost['tweaks_lost']}  {lost['review']!r}")

    print(f"\n2. Extraction vs hand labels ({name})")
    for label in ("strict", "lenient"):
        r = ext[label]
        print(f"   {label:8} precision {pct(r['precision'])}  recall {pct(r['recall'])}  F1 {pct(r['f1'])}   (tp {r['tp']}, fp {r['fp']}, fn {r['fn']})")
    s = ext["strict"]
    print("   recall by type: " + ", ".join(f"{t} {pct(v).strip()}" for t, v in s["recall_by_type"].items()))
    print(f"   false alarms on reviews with no tweak: {pct(s['false_alarm_rate']).strip()} of {s['reviews_without_tweaks']}")

    print("\n3. Edit grounding: does `find` point at a real line?")
    if show_grounding:
        print(f"   {ground['grounded']}/{ground['edits']} edits ground to a line ({pct(ground['grounded_rate']).strip()})")
    else:
        print("   n/a for the baseline: it emits placeholder edits, not real ones")

    print("\n4. RecipeModifier (offline): is the intended line edited?")
    print(f"   exact match {mod['exact_match']}/{mod['cases']} ({pct(mod['exact_match_rate']).strip()}), "
          f"silent wrong edits {mod['silent_wrong_edits']}, edits not applied {mod['edits_not_applied']}")
    for f in mod["failures"]:
        print(f"   FAIL {f['id']}: {f['kind']}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--predictor", choices=["baseline", "llm-pipeline", "llm-model"], default="baseline")
    ap.add_argument("--predictions", help="score a saved predictions file instead of running a predictor")
    ap.add_argument("--save", help="write the predictions used to this file")
    args = ap.parse_args()

    logger.remove()
    logger.add(lambda m: print(m, end=""), level="WARNING")

    golden = load_json("golden_extraction.json")
    problems = check_golden_integrity(golden)
    if problems:
        raise SystemExit("golden set is out of sync with data/:\n  " + "\n  ".join(problems))

    if args.predictions:
        preds, name = load_predictions(args.predictions), f"saved: {args.predictions}"
    elif args.predictor == "baseline":
        preds, name = baseline_predictions(golden), "keyword baseline, no LLM"
    else:
        if not any(os.getenv(k) for k in ("OPENAI_API_KEY", "GROQ_API_KEY", "GEMINI_API_KEY")):
            raise SystemExit(
                f"--predictor {args.predictor} calls a real LLM: set OPENAI_API_KEY, GROQ_API_KEY "
                "or GEMINI_API_KEY (or use --predictor baseline)."
            )
        preds, name = llm_predictions(golden, args.predictor), args.predictor

    if args.save:
        save_predictions(args.save, preds)
    print_report(name, golden, preds, show_grounding=args.predictions is not None or args.predictor != "baseline")


if __name__ == "__main__":
    main()
