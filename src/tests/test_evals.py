"""
Tests for the eval harness (src/evals) and the golden sets it scores against.

Two kinds of test live here:
- Metric tests: prove the scoring is right (a perfect answer scores 1.0, a weak one scores lower,
  matching and edge rules behave). A metric that cannot fail would make the eval worthless.
- Regression gates: the modifier must keep editing the intended line, and the golden set must stay
  in sync with the committed data.
"""

import pytest
from loguru import logger

from evals.baseline import keyword_baseline, oracle_from_gold
from evals.metrics import (
    check_golden_integrity,
    load_json,
    load_recipe_json,
    matches,
    score_edit_grounding,
    score_extraction,
    score_modifier,
    score_review,
    score_source_selection,
)
from llm_pipeline.models import ModificationEdit, ModificationObject


@pytest.fixture(autouse=True)
def quiet_modifier_logs():
    logger.disable("llm_pipeline")
    yield
    logger.enable("llm_pipeline")


@pytest.fixture(scope="module")
def golden():
    return load_json("golden_extraction.json")


def mod(mod_type: str, text: str, find: str = "x", target: str = "ingredients") -> ModificationObject:
    return ModificationObject(
        modification_type=mod_type,
        reasoning=text,
        edits=[ModificationEdit(target=target, operation="replace", find=find, replace="y")],
    )


def gold(mod_type: str, terms, scored: bool = True) -> dict:
    return {"modification_type": mod_type, "must_mention": terms, "status": "applied", "scored": scored}


# ---- golden data integrity -------------------------------------------------------------------

def test_golden_set_matches_committed_data(golden):
    assert check_golden_integrity(golden) == []


def test_golden_set_covers_every_review_of_the_labeled_recipes(golden):
    for rid in {c["recipe_id"] for c in golden["cases"]}:
        labeled = {c["review_index"] for c in golden["cases"] if c["recipe_id"] == rid}
        assert labeled == set(range(len(load_recipe_json(rid)["reviews"]))), f"recipe {rid} has unlabeled reviews"


def test_golden_set_has_both_positives_and_negatives(golden):
    assert sum(1 for c in golden["cases"] if c["tweaks"]) >= 10
    assert sum(1 for c in golden["cases"] if not c["tweaks"]) >= 3


def test_integrity_check_detects_drifted_review_text():
    bad = {"cases": [{"recipe_id": "10813", "review_index": 0, "review_prefix": "this is not the review", "tweaks": []}]}
    assert any("changed since it was labeled" in p for p in check_golden_integrity(bad))


# ---- matching rules --------------------------------------------------------------------------

def test_match_requires_type_when_strict_but_not_when_lenient():
    g = gold("addition", ["egg yolk"])
    wrong_type = mod("quantity_adjustment", "added an extra egg yolk")
    assert matches(wrong_type, g, strict=False)
    assert not matches(wrong_type, g, strict=True)


def test_match_requires_a_term_even_when_the_type_is_right():
    assert not matches(mod("addition", "added vanilla"), gold("addition", ["egg yolk"]))


def test_match_looks_in_edit_text_not_just_reasoning():
    m = mod("addition", "improves chew", find="1 egg yolk")
    assert matches(m, gold("addition", ["egg yolk"]))


def test_matching_is_one_to_one():
    """Two gold tweaks must not both be satisfied by a single prediction."""
    res = score_review([mod("addition", "egg yolk and cinnamon")], [gold("addition", ["egg yolk"]), gold("addition", ["cinnamon"])], strict=True)
    assert (res["tp"], res["fn"], res["fp"]) == (1, 1, 0)


def test_extra_prediction_is_a_false_positive():
    res = score_review([mod("addition", "egg yolk"), mod("addition", "pecans")], [gold("addition", ["egg yolk"])], strict=True)
    assert (res["tp"], res["fp"], res["fn"]) == (1, 1, 0)


def test_prediction_matching_an_unscored_tweak_is_ignored_not_penalised():
    res = score_review([mod("ingredient_substitution", "different frosting")], [gold("ingredient_substitution", ["frosting"], scored=False)], strict=True)
    assert (res["tp"], res["fp"], res["fn"], res["ignored"]) == (0, 0, 0, 1)


# ---- extraction scoring ----------------------------------------------------------------------

def test_oracle_predictions_score_perfectly(golden):
    preds = {(c["recipe_id"], c["review_index"]): oracle_from_gold(c["tweaks"]) for c in golden["cases"]}
    r = score_extraction(golden, preds)
    for label in ("strict", "lenient"):
        assert (r[label]["precision"], r[label]["recall"], r[label]["f1"]) == (1.0, 1.0, 1.0)
    assert r["strict"]["false_alarm_rate"] == 0.0


def test_no_predictions_score_zero_recall(golden):
    r = score_extraction(golden, {})
    assert r["strict"]["recall"] == 0.0 and r["strict"]["tp"] == 0


def test_flagging_every_review_is_caught_as_false_alarms(golden):
    preds = {(c["recipe_id"], c["review_index"]): [mod("addition", "something")] for c in golden["cases"]}
    r = score_extraction(golden, preds)
    assert r["strict"]["false_alarm_rate"] == 1.0
    assert r["strict"]["precision"] < 0.2


def test_keyword_baseline_is_better_than_nothing_but_not_perfect(golden):
    """Proves the metrics can tell a weak extractor from a perfect one."""
    preds = {
        (c["recipe_id"], c["review_index"]): keyword_baseline(load_recipe_json(c["recipe_id"])["reviews"][c["review_index"]]["text"])
        for c in golden["cases"]
    }
    f1 = score_extraction(golden, preds)["strict"]["f1"]
    assert 0.3 < f1 < 1.0


# ---- source selection (the recall ceiling) ---------------------------------------------------

def test_source_selection_ceiling_is_a_valid_rate_and_lists_what_is_lost(golden):
    r = score_source_selection(golden)
    assert 0.0 < r["tweak_recall_ceiling"] <= 1.0
    assert r["tweaks_lost_before_llm"] == sum(l["tweaks_lost"] for l in r["lost_reviews"])


def test_source_selection_does_not_regress_below_the_measured_ceiling(golden):
    """Measured at 28/31 tweaks reaching the LLM. Lowering it means a change to review selection dropped tweaks."""
    assert score_source_selection(golden)["tweak_recall_ceiling"] >= 0.90


# ---- edit grounding --------------------------------------------------------------------------

def test_grounding_counts_real_and_invented_lines():
    real = mod("removal", "r", find="2 teaspoons hot water")
    invented = mod("removal", "r", find="3 tablespoons maple syrup")
    r = score_edit_grounding({("10813", 0): [real, invented]})
    assert (r["edits"], r["grounded"]) == (2, 1)
    assert r["ungrounded"] == ["10813: ingredients: '3 tablespoons maple syrup'"]


# ---- modifier regression gate ----------------------------------------------------------------

def test_modifier_applies_every_golden_edit_to_the_intended_line():
    r = score_modifier(load_json("golden_modifier.json")["cases"])
    assert r["failures"] == [], r["failures"]


def test_modifier_never_makes_a_silent_wrong_edit():
    assert score_modifier(load_json("golden_modifier.json")["cases"])["silent_wrong_edits"] == 0


def test_modifier_scoring_detects_a_wrong_result():
    """If the expected list is wrong the scorer must report it, otherwise the gate above proves nothing."""
    case = dict(load_json("golden_modifier.json")["cases"][0])
    case["expected"] = list(case["expected"][:-1])  # drop a line from the expected result
    r = score_modifier([case])
    assert r["exact_match"] == 0 and len(r["failures"]) == 1
