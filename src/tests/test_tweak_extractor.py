"""
Unit tests for multi-modification extraction.

These tests mock the OpenAI client entirely (no network calls / no API key
required) so they can run in CI or any environment. They exist to prove the core
bug fix: a review describing several independent changes must be extracted as
several discrete ModificationObject instances, not merged into one.
"""

import json
from unittest.mock import MagicMock

import pytest

from llm_pipeline.models import Recipe, Review
from llm_pipeline.tweak_extractor import TweakExtractor


def make_llm_response(payload: dict) -> MagicMock:
    """Build a fake OpenAI ChatCompletion response object."""
    message = MagicMock()
    message.content = json.dumps(payload)
    choice = MagicMock()
    choice.message = message
    response = MagicMock()
    response.choices = [choice]
    return response


@pytest.fixture
def cookie_recipe() -> Recipe:
    return Recipe(
        recipe_id="10813",
        title="Best Chocolate Chip Cookies",
        ingredients=[
            "1 cup butter, softened",
            "1 cup white sugar",
            "1 cup packed brown sugar",
            "2 eggs",
            "1 teaspoon baking soda",
            "2 teaspoons hot water",
            "0.5 teaspoon salt",
        ],
        instructions=[
            "Preheat the oven to 350 degrees F (175 degrees C)",
            "Bake in the preheated oven until edges are nicely browned, about 10 minutes",
        ],
    )


@pytest.fixture
def extractor() -> TweakExtractor:
    return TweakExtractor(api_key="test-key-not-used")


def test_compound_review_splits_into_multiple_modification_types(extractor, cookie_recipe):
    """'I added an egg and halved the sugar' style compound review: the two
    clauses describe DIFFERENT modification types (addition + quantity_adjustment)
    and must come back as two separate ModificationObject entries, each with a
    single modification_type - never merged into one."""
    review = Review(
        text="I added an extra egg and used half a cup of white sugar instead of a full cup.",
        rating=5,
        has_modification=True,
    )

    payload = {
        "modifications": [
            {
                "modification_type": "addition",
                "reasoning": "Extra egg adds richness and chewiness",
                "edits": [
                    {
                        "target": "ingredients",
                        "operation": "add_after",
                        "find": "2 eggs",
                        "add": "1 additional egg",
                    }
                ],
            },
            {
                "modification_type": "quantity_adjustment",
                "reasoning": "Less white sugar balances sweetness",
                "edits": [
                    {
                        "target": "ingredients",
                        "operation": "replace",
                        "find": "1 cup white sugar",
                        "replace": "0.5 cup white sugar",
                    }
                ],
            },
        ]
    }
    extractor.client.chat.completions.create = MagicMock(
        return_value=make_llm_response(payload)
    )

    modifications = extractor.extract_modifications(review, cookie_recipe)

    assert len(modifications) == 2, "compound review must yield 2 discrete modifications, not 1 merged object"
    types = {m.modification_type for m in modifications}
    assert types == {"addition", "quantity_adjustment"}


def test_four_part_compound_review_all_four_captured(extractor, cookie_recipe):
    """Regression test for the exact review from the sample data:
    '(1) half cup sugar + 1.5 cups brown sugar; (2) omitted water; (3) added
    cream of tartar; (4) refrigerated batter' - all 4 discrete changes must be
    captured, not just the first/dominant one."""
    review = Review(
        text=(
            'These are awesome cookies. I followed the advice of others by making '
            'the following tweaks: (1) I used a half cup of sugar and one-and-a-half '
            "cups of brown sugar; (2) I omitted the water; (3) I added a teaspoon of "
            "cream of tartar to the batter; (4) I refrigerated the batter for at "
            "least an hour before scooping and baking."
        ),
        rating=5,
        has_modification=True,
    )

    payload = {
        "modifications": [
            {
                "modification_type": "quantity_adjustment",
                "reasoning": "Adjusts sugar ratio for chewier cookies",
                "edits": [
                    {"target": "ingredients", "operation": "replace", "find": "1 cup white sugar", "replace": "0.5 cup white sugar"},
                    {"target": "ingredients", "operation": "replace", "find": "1 cup packed brown sugar", "replace": "1.5 cups packed brown sugar"},
                ],
            },
            {
                "modification_type": "removal",
                "reasoning": "Omitting water prevents spreading",
                "edits": [
                    {"target": "ingredients", "operation": "remove", "find": "2 teaspoons hot water"},
                ],
            },
            {
                "modification_type": "addition",
                "reasoning": "Cream of tartar helps cookies keep their shape",
                "edits": [
                    {"target": "ingredients", "operation": "add_after", "find": "0.5 teaspoon salt", "add": "1 teaspoon cream of tartar"},
                ],
            },
            {
                "modification_type": "technique_change",
                "reasoning": "Refrigerating the batter reduces spread during baking",
                "edits": [
                    {"target": "instructions", "operation": "add_after", "find": "Preheat the oven to 350 degrees F (175 degrees C)", "add": "Refrigerate the batter for at least 1 hour before scooping"},
                ],
            },
        ]
    }
    extractor.client.chat.completions.create = MagicMock(
        return_value=make_llm_response(payload)
    )

    modifications = extractor.extract_modifications(review, cookie_recipe)

    assert len(modifications) == 4, "all 4 discrete tweaks in the review must be captured"
    types = [m.modification_type for m in modifications]
    assert types == ["quantity_adjustment", "removal", "addition", "technique_change"]


def test_extract_modifications_from_reviews_uses_one_batched_call(extractor, cookie_recipe):
    """Cost optimization: N reviews must cost exactly 1 LLM call (not N), via
    extract_modifications_batch, with each modification correctly attributed back
    to its source review by review_index."""
    review_a = Review(text="Review A: added egg and halved sugar", has_modification=True)
    review_b = Review(text="Review B: omitted nuts and baked hotter", has_modification=True)

    batch_payload = {
        "modifications": [
            {"review_index": 0, "modification_type": "addition", "reasoning": "r1", "edits": [{"target": "ingredients", "operation": "add_after", "find": "2 eggs", "add": "1 egg"}]},
            {"review_index": 0, "modification_type": "quantity_adjustment", "reasoning": "r2", "edits": [{"target": "ingredients", "operation": "replace", "find": "1 cup white sugar", "replace": "0.5 cup white sugar"}]},
            {"review_index": 1, "modification_type": "removal", "reasoning": "r3", "edits": [{"target": "ingredients", "operation": "remove", "find": "0.5 teaspoon salt"}]},
            {"review_index": 1, "modification_type": "technique_change", "reasoning": "r4", "edits": [{"target": "instructions", "operation": "replace", "find": "350 degrees F", "replace": "375 degrees F"}]},
        ]
    }

    mock_create = MagicMock(return_value=make_llm_response(batch_payload))
    extractor.client.chat.completions.create = mock_create

    results = extractor.extract_modifications_from_reviews([review_a, review_b], cookie_recipe)

    assert mock_create.call_count == 1, "must cost exactly 1 LLM call for N reviews, not N calls"
    assert len(results) == 4
    assert [m.modification_type for m, _ in results] == [
        "addition", "quantity_adjustment", "removal", "technique_change"
    ]
    # attribution preserved via review_index: first two point back to review_a, last two to review_b
    assert results[0][1] is review_a and results[1][1] is review_a
    assert results[2][1] is review_b and results[3][1] is review_b


def test_extract_modifications_from_reviews_falls_back_per_review_on_batch_failure(extractor, cookie_recipe):
    """If the batched call fails entirely (e.g. malformed output after retries),
    fall back to one call per review rather than losing the modifications - costs
    more, but stays resilient."""
    review_a = Review(text="Review A: added egg", has_modification=True)
    review_b = Review(text="Review B: halved sugar", has_modification=True)

    bad_response = MagicMock()
    bad_message = MagicMock()
    bad_message.content = "not valid json {{{"
    bad_choice = MagicMock()
    bad_choice.message = bad_message
    bad_response.choices = [bad_choice]

    per_review_payload_a = {"modifications": [{"modification_type": "addition", "reasoning": "r1", "edits": [{"target": "ingredients", "operation": "add_after", "find": "2 eggs", "add": "1 egg"}]}]}
    per_review_payload_b = {"modifications": [{"modification_type": "quantity_adjustment", "reasoning": "r2", "edits": [{"target": "ingredients", "operation": "replace", "find": "1 cup white sugar", "replace": "0.5 cup white sugar"}]}]}

    # 3 bad responses exhaust extract_modifications_batch's retries (max_retries=2
    # -> 3 attempts), then 1 good response per subsequent per-review call.
    extractor.client.chat.completions.create = MagicMock(
        side_effect=[
            bad_response, bad_response, bad_response,
            make_llm_response(per_review_payload_a),
            make_llm_response(per_review_payload_b),
        ]
    )

    results = extractor.extract_modifications_from_reviews([review_a, review_b], cookie_recipe)

    assert len(results) == 2
    assert [m.modification_type for m, _ in results] == ["addition", "quantity_adjustment"]
    assert results[0][1] is review_a
    assert results[1][1] is review_b


def test_single_modification_review_returns_one_entry(extractor, cookie_recipe):
    """A review with only one discrete change should return exactly one entry -
    the fix must not force-split reviews that only describe a single change."""
    review = Review(text="I baked at 375 instead of 350.", has_modification=True)
    payload = {
        "modifications": [
            {"modification_type": "technique_change", "reasoning": "crispier", "edits": [
                {"target": "instructions", "operation": "replace", "find": "350 degrees F", "replace": "375 degrees F"}
            ]}
        ]
    }
    extractor.client.chat.completions.create = MagicMock(return_value=make_llm_response(payload))

    modifications = extractor.extract_modifications(review, cookie_recipe)
    assert len(modifications) == 1
    assert modifications[0].modification_type == "technique_change"


def test_lenient_bare_object_fallback(extractor, cookie_recipe):
    """If the model ignores instructions and returns a bare ModificationObject
    (no 'modifications' wrapper), the extractor should still accept it as a
    single-item list rather than raising a validation error."""
    review = Review(text="I added cinnamon.", has_modification=True)
    payload = {
        "modification_type": "addition",
        "reasoning": "adds warmth",
        "edits": [{"target": "ingredients", "operation": "add_after", "find": "2 eggs", "add": "1 tsp cinnamon"}],
    }
    extractor.client.chat.completions.create = MagicMock(return_value=make_llm_response(payload))

    modifications = extractor.extract_modifications(review, cookie_recipe)
    assert len(modifications) == 1
    assert modifications[0].modification_type == "addition"


def test_no_modification_flag_returns_empty(extractor, cookie_recipe):
    review = Review(text="Great recipe, thanks!", has_modification=False)
    assert extractor.extract_modifications(review, cookie_recipe) == []


def test_invalid_json_returns_empty_after_retries(extractor, cookie_recipe):
    review = Review(text="I changed something.", has_modification=True)
    bad_response = MagicMock()
    bad_message = MagicMock()
    bad_message.content = "not valid json {{{"
    bad_choice = MagicMock()
    bad_choice.message = bad_message
    bad_response.choices = [bad_choice]

    extractor.client.chat.completions.create = MagicMock(return_value=bad_response)

    modifications = extractor.extract_modifications(review, cookie_recipe, max_retries=1)
    assert modifications == []
    assert extractor.client.chat.completions.create.call_count == 2  # initial + 1 retry
