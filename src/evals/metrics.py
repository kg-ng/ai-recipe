"""
Metrics for scoring the recipe-enhancement pipeline against hand-labeled golden sets.

Four things are measured, each separately so a regression can be located:

1. Source selection (the gate): of the tweaks a human found in the reviews, how many
   even reach the LLM? This is a hard ceiling on recall, whatever the model does.
2. Extraction quality: precision / recall / F1 of the extracted modifications against
   the golden tweaks, strict (type + term must match) and lenient (term only).
3. Edit grounding: does the `find` text of each extracted edit point at a real line?
4. Modifier correctness: does RecipeModifier apply an edit to the intended line?

Everything here is pure and offline. Predictions come from outside (an LLM run, a
saved file, or a baseline), so scoring needs no API key.
"""

import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from llm_pipeline.models import ModificationObject, Recipe
from llm_pipeline.pipeline import LLMAnalysisPipeline
from llm_pipeline.recipe_modifier import RecipeModifier

EVALS_DIR = Path(__file__).resolve().parent
DATA_DIR = EVALS_DIR.parent.parent / "data"

CaseKey = Tuple[str, int]  # (recipe_id, review_index)


def load_json(name: str) -> Dict[str, Any]:
    with open(EVALS_DIR / name, "r", encoding="utf-8") as f:
        return json.load(f)


def load_recipe_json(recipe_id: str) -> Dict[str, Any]:
    matches = sorted(DATA_DIR.glob(f"recipe_{recipe_id}_*.json"))
    if not matches:
        raise FileNotFoundError(f"no recipe file for id {recipe_id} in {DATA_DIR}")
    with open(matches[0], "r", encoding="utf-8") as f:
        return json.load(f)


def prediction_text(mod: ModificationObject) -> str:
    """Everything a prediction says, lowercased, for term matching."""
    parts = [mod.reasoning]
    for e in mod.edits:
        parts += [e.find, e.replace or "", e.add or ""]
    return " ".join(parts).lower()


def matches(mod: ModificationObject, gold: Dict[str, Any], strict: bool = True) -> bool:
    if strict and mod.modification_type != gold["modification_type"]:
        return False
    text = prediction_text(mod)
    return any(term.lower() in text for term in gold["must_mention"])


def _safe_div(n: float, d: float) -> float:
    return n / d if d else 0.0


def _prf(tp: int, fp: int, fn: int) -> Dict[str, float]:
    p, r = _safe_div(tp, tp + fp), _safe_div(tp, tp + fn)
    return {"tp": tp, "fp": fp, "fn": fn, "precision": p, "recall": r, "f1": _safe_div(2 * p * r, p + r)}


def score_review(
    preds: Sequence[ModificationObject], gold_tweaks: Sequence[Dict[str, Any]], strict: bool
) -> Dict[str, Any]:
    """One-to-one greedy matching of predictions to gold tweaks for a single review."""
    used = set()
    tp, missed, found = 0, [], []
    scored = [g for g in gold_tweaks if g.get("scored", True)]
    unscored = [g for g in gold_tweaks if not g.get("scored", True)]

    for g in scored:
        hit = next((i for i, p in enumerate(preds) if i not in used and matches(p, g, strict)), None)
        if hit is None:
            missed.append(g)
        else:
            used.add(hit)
            found.append(g)
            tp += 1

    ignored = 0
    for g in unscored:  # predictions matching a too-vague gold tweak are neither right nor wrong
        hit = next((i for i, p in enumerate(preds) if i not in used and matches(p, g, strict)), None)
        if hit is not None:
            used.add(hit)
            ignored += 1

    return {"tp": tp, "fp": len(preds) - len(used), "fn": len(missed), "ignored": ignored, "missed": missed, "found": found}


def score_extraction(
    golden: Dict[str, Any], predictions: Dict[CaseKey, List[ModificationObject]]
) -> Dict[str, Any]:
    """Score predictions (keyed by (recipe_id, review_index)) against the golden cases."""
    report: Dict[str, Any] = {}
    for label, strict in (("strict", True), ("lenient", False)):
        tp = fp = fn = 0
        by_type: Dict[str, List[int]] = defaultdict(lambda: [0, 0])  # type -> [found, total]
        negatives = false_alarm_reviews = 0
        for case in golden["cases"]:
            key = (case["recipe_id"], case["review_index"])
            preds = predictions.get(key, [])
            res = score_review(preds, case["tweaks"], strict)
            tp, fp, fn = tp + res["tp"], fp + res["fp"], fn + res["fn"]
            for g in res["found"]:
                by_type[g["modification_type"]][0] += 1
                by_type[g["modification_type"]][1] += 1
            for g in res["missed"]:
                by_type[g["modification_type"]][1] += 1
            if not case["tweaks"]:
                negatives += 1
                false_alarm_reviews += 1 if preds else 0
        report[label] = {
            **_prf(tp, fp, fn),
            "recall_by_type": {t: _safe_div(f, n) for t, (f, n) in sorted(by_type.items())},
            "reviews_without_tweaks": negatives,
            "false_alarm_rate": _safe_div(false_alarm_reviews, negatives),
        }
    return report


def _select_sources(recipe_data: Dict[str, Any]) -> List[str]:
    """Texts the real pipeline would send to the LLM. Reuses the pipeline's own selection logic
    (featured_tweaks first, has_modification fallback), then the extractor's has_modification filter."""
    pipeline = object.__new__(LLMAnalysisPipeline)  # selection methods use no instance state
    selected = pipeline.select_source_reviews(recipe_data)
    return [r.text for r in selected if r.has_modification]


def score_source_selection(golden: Dict[str, Any]) -> Dict[str, Any]:
    """How many hand-labeled tweaks survive the pipeline's review selection (the recall ceiling)."""
    cache: Dict[str, List[str]] = {}
    tweaks_total = tweaks_reached = reviews_total = reviews_reached = 0
    lost: List[Dict[str, Any]] = []
    for case in golden["cases"]:
        scored = [t for t in case["tweaks"] if t.get("scored", True)]
        if not scored:
            continue
        rid = case["recipe_id"]
        data = load_recipe_json(rid)
        sources = cache.setdefault(rid, _select_sources(data))
        text = data["reviews"][case["review_index"]]["text"]
        reviews_total += 1
        tweaks_total += len(scored)
        if text in sources:
            reviews_reached += 1
            tweaks_reached += len(scored)
        else:
            lost.append({"recipe_id": rid, "review_index": case["review_index"], "tweaks_lost": len(scored), "review": text[:80]})
    return {
        "reviews_with_tweaks": reviews_total,
        "reviews_reaching_llm": reviews_reached,
        "tweak_recall_ceiling": _safe_div(tweaks_reached, tweaks_total),
        "tweaks_total": tweaks_total,
        "tweaks_lost_before_llm": tweaks_total - tweaks_reached,
        "lost_reviews": lost,
    }


def score_edit_grounding(
    predictions: Dict[CaseKey, List[ModificationObject]], modifier: Optional[RecipeModifier] = None
) -> Dict[str, Any]:
    """Share of predicted replace/remove/add_after edits whose `find` text resolves to a real recipe line."""
    modifier = modifier or RecipeModifier()
    total = grounded = 0
    ungrounded: List[str] = []
    for (rid, _idx), mods in predictions.items():
        data = load_recipe_json(rid)
        lines = {"ingredients": data["ingredients"], "instructions": data["instructions"]}
        for mod in mods:
            for e in mod.edits:
                total += 1
                match, _i, _s = modifier.find_best_match(e.find, lines[e.target])
                if match:
                    grounded += 1
                else:
                    ungrounded.append(f"{rid}: {e.target}: {e.find!r}")
    return {"edits": total, "grounded": grounded, "grounded_rate": _safe_div(grounded, total), "ungrounded": ungrounded}


def score_modifier(cases: Sequence[Dict[str, Any]], modifier: Optional[RecipeModifier] = None) -> Dict[str, Any]:
    """Apply each golden edit and compare the resulting list with the expected one.

    `silent_wrong_edits` is the dangerous bucket: the modifier changed something, reported success,
    but did not produce the expected result (typically the wrong line was edited)."""
    modifier = modifier or RecipeModifier()
    from llm_pipeline.models import ModificationEdit

    exact = silent_wrong = no_change_expected_change = 0
    failures: List[Dict[str, Any]] = []
    for c in cases:
        edit = ModificationEdit(**c["edit"])
        before = list(c[edit.target])
        after, _records = modifier.apply_edit(edit, before)
        if after == c["expected"]:
            exact += 1
            continue
        if after != before:
            silent_wrong += 1
            kind = "silent_wrong_edit"
        else:
            no_change_expected_change += 1
            kind = "edit_not_applied"
        failures.append({"id": c["id"], "kind": kind, "got": after, "expected": c["expected"]})
    n = len(cases)
    return {
        "cases": n,
        "exact_match": exact,
        "exact_match_rate": _safe_div(exact, n),
        "silent_wrong_edits": silent_wrong,
        "edits_not_applied": no_change_expected_change,
        "failures": failures,
    }


def check_golden_integrity(golden: Dict[str, Any]) -> List[str]:
    """Problems that would make the golden set silently wrong: a review index out of range, or
    review text that no longer matches the committed data (the labels would then point at the wrong review)."""
    problems: List[str] = []
    for case in golden["cases"]:
        rid, idx = case["recipe_id"], case["review_index"]
        try:
            reviews = load_recipe_json(rid)["reviews"]
        except FileNotFoundError as e:
            problems.append(str(e))
            continue
        if idx >= len(reviews):
            problems.append(f"{rid}[{idx}]: review index out of range ({len(reviews)} reviews)")
        elif not reviews[idx]["text"].startswith(case["review_prefix"]):
            problems.append(f"{rid}[{idx}]: review text changed since it was labeled")
    return problems
