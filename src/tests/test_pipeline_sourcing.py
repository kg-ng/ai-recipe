"""
Tests for how the pipeline selects which reviews to extract modifications from,
and how it behaves end-to-end (including the "no community tweaks available"
edge case that previously caused 2 of the 5 sample recipes to be silently
dropped from data/enhanced/).
"""

from unittest.mock import MagicMock

from llm_pipeline.models import ModificationEdit, ModificationObject, Review
from llm_pipeline.pipeline import LLMAnalysisPipeline


def make_pipeline(tmp_path) -> LLMAnalysisPipeline:
    pipeline = LLMAnalysisPipeline.__new__(LLMAnalysisPipeline)
    # Avoid __init__'s real TweakExtractor(OpenAI(...)) construction requiring an
    # API key; wire up the pieces manually with a mocked extractor.
    from llm_pipeline.recipe_modifier import RecipeModifier
    from llm_pipeline.enhanced_recipe_generator import EnhancedRecipeGenerator
    from pathlib import Path

    pipeline.output_dir = Path(tmp_path)
    pipeline.output_dir.mkdir(parents=True, exist_ok=True)
    pipeline.tweak_extractor = MagicMock()
    pipeline.recipe_modifier = RecipeModifier()
    pipeline.enhanced_generator = EnhancedRecipeGenerator(pipeline_version="test")
    return pipeline


def test_select_source_reviews_prefers_featured_tweaks(tmp_path):
    pipeline = make_pipeline(tmp_path)
    recipe_data = {
        "reviews": [
            {"text": "random unfeatured tweak", "has_modification": True, "is_featured": False},
        ],
        "featured_tweaks": [
            {"text": "the real featured tweak", "has_modification": True, "is_featured": True},
        ],
    }
    selected = pipeline.select_source_reviews(recipe_data)
    assert len(selected) == 1
    assert selected[0].text == "the real featured tweak"
    assert selected[0].is_featured is True


def test_select_source_reviews_falls_back_when_no_featured_tweaks(tmp_path):
    pipeline = make_pipeline(tmp_path)
    recipe_data = {
        "reviews": [
            {"text": "no modification here", "has_modification": False},
            {"text": "this one has a tweak", "has_modification": True},
        ],
        "featured_tweaks": [],
    }
    selected = pipeline.select_source_reviews(recipe_data)
    assert len(selected) == 1
    assert selected[0].text == "this one has a tweak"


def test_select_source_reviews_empty_when_no_reviews_at_all(tmp_path):
    """Reproduces the plum-jam / mango-marinade sample recipes: zero reviews,
    zero featured_tweaks."""
    pipeline = make_pipeline(tmp_path)
    recipe_data = {"reviews": [], "featured_tweaks": []}
    assert pipeline.select_source_reviews(recipe_data) == []


def _sample_recipe_data(with_tweaks: bool) -> dict:
    base = {
        "recipe_id": "999",
        "title": "Test Recipe",
        "ingredients": ["1 cup flour", "1 cup sugar"],
        "instructions": ["Mix", "Bake"],
        "reviews": [],
        "featured_tweaks": [],
    }
    if with_tweaks:
        base["featured_tweaks"] = [
            {"text": "added an egg and halved the sugar", "has_modification": True, "is_featured": True},
        ]
    return base


def test_process_single_recipe_with_no_tweaks_returns_enhanced_recipe_not_none(tmp_path, monkeypatch):
    """Core scale fix: a recipe with zero reviews/featured_tweaks must still
    produce an EnhancedRecipe (0 modifications, honest message) instead of the
    pipeline returning None and silently vanishing from data/enhanced/."""
    pipeline = make_pipeline(tmp_path)
    recipe_data = _sample_recipe_data(with_tweaks=False)

    monkeypatch.setattr(pipeline, "load_recipe_data", lambda path: recipe_data)

    result = pipeline.process_single_recipe("fake_path.json", save_output=True)

    assert result is not None
    assert result.modifications_applied == []
    assert result.enhancement_summary.total_changes == 0
    assert "No community-tested modifications" in result.enhancement_summary.expected_impact
    # ingredients/instructions unchanged since nothing was applied
    assert result.ingredients == recipe_data["ingredients"]


def test_process_single_recipe_applies_multiple_modifications_from_one_review(tmp_path, monkeypatch):
    """End-to-end: a compound review split into 2 modifications by the
    extractor must result in 2 ModificationApplied entries and both edits
    actually applied to the output recipe."""
    pipeline = make_pipeline(tmp_path)
    recipe_data = _sample_recipe_data(with_tweaks=True)
    monkeypatch.setattr(pipeline, "load_recipe_data", lambda path: recipe_data)

    source_review = Review(text="added an egg and halved the sugar", has_modification=True, is_featured=True)
    mod_1 = ModificationObject(
        modification_type="addition",
        reasoning="egg adds richness",
        edits=[ModificationEdit(target="ingredients", operation="add_after", find="1 cup flour", add="1 extra egg")],
    )
    mod_2 = ModificationObject(
        modification_type="quantity_adjustment",
        reasoning="less sugar",
        edits=[ModificationEdit(target="ingredients", operation="replace", find="1 cup sugar", replace="0.5 cup sugar")],
    )
    pipeline.tweak_extractor.extract_modifications_from_reviews = MagicMock(
        return_value=[(mod_1, source_review), (mod_2, source_review)]
    )

    result = pipeline.process_single_recipe("fake_path.json", save_output=False)

    assert result is not None
    assert len(result.modifications_applied) == 2
    assert {m.modification_type for m in result.modifications_applied} == {"addition", "quantity_adjustment"}
    assert "1 extra egg" in result.ingredients
    assert "0.5 cup sugar" in result.ingredients
    assert "1 cup sugar" not in result.ingredients
