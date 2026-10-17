#!/usr/bin/env python3
"""
LLM Analysis Pipeline Test Script

This script tests the complete 3-step pipeline with support for both single recipe
testing and full recipe directory validation.

Usage:
    python test_pipeline.py single    # Run the single chocolate chip cookie recipe
    python test_pipeline.py all       # Run all recipes in the data directory

Under pytest, the live tests below only run when RUN_LIVE_LLM_TESTS=1 and an LLM API
key is set, because they call a real (possibly paid) provider. They write to a temp
directory, never to the tracked data/enhanced/ files.
"""

import os
import sys
from pathlib import Path

import pytest
from dotenv import load_dotenv

from llm_pipeline.pipeline import LLMAnalysisPipeline
from loguru import logger

# Load environment variables from .env file
load_dotenv()

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data"
DEFAULT_OUTPUT_DIR = DATA_DIR / "enhanced"
LLM_KEY_VARS = ("OPENAI_API_KEY", "GROQ_API_KEY", "GEMINI_API_KEY")


def has_llm_key() -> bool:
    """True if any supported LLM provider key is configured."""
    return any(os.getenv(name) for name in LLM_KEY_VARS)


def run_single_recipe(output_dir: Path = DEFAULT_OUTPUT_DIR) -> bool:
    """Run the pipeline on the chocolate chip cookie recipe. Returns True on success."""

    if not has_llm_key():
        logger.error(f"No LLM API key set (looked for: {', '.join(LLM_KEY_VARS)})")
        logger.info("Please set one in a .env file")
        return False

    try:
        pipeline = LLMAnalysisPipeline(output_dir=str(output_dir))
        logger.info("Pipeline initialized successfully")
    except Exception as e:
        logger.error(f"Failed to initialize pipeline: {e}")
        return False

    recipe_file = DATA_DIR / "recipe_10813_best-chocolate-chip-cookies.json"
    if not recipe_file.exists():
        logger.error(f"Recipe file not found: {recipe_file}")
        return False

    logger.info(f"Testing with recipe file: {recipe_file}")

    try:
        enhanced_recipe = pipeline.process_single_recipe(
            recipe_file=str(recipe_file),
            save_output=True
        )

        if enhanced_recipe:
            logger.success("✓ Single recipe test successful!")
            logger.info(f"Enhanced recipe: {enhanced_recipe.title}")
            logger.info(f"Modifications applied: {len(enhanced_recipe.modifications_applied)}")
            logger.info(f"Total changes: {enhanced_recipe.enhancement_summary.total_changes}")
            logger.info(f"Expected impact: {enhanced_recipe.enhancement_summary.expected_impact}")
            return True
        else:
            logger.error("✗ Single recipe test failed - no enhanced recipe generated")
            return False

    except Exception as e:
        logger.error(f"Single recipe test failed with error: {e}")
        import traceback
        traceback.print_exc()
        return False


def run_all_recipes(output_dir: Path = DEFAULT_OUTPUT_DIR) -> bool:
    """Run the pipeline on every scraped recipe. Returns True if at least one was enhanced."""

    if not has_llm_key():
        logger.error(f"No LLM API key set (looked for: {', '.join(LLM_KEY_VARS)})")
        logger.info("Please set one in a .env file")
        return False

    try:
        pipeline = LLMAnalysisPipeline(output_dir=str(output_dir))
        logger.info("Pipeline initialized successfully")
    except Exception as e:
        logger.error(f"Failed to initialize pipeline: {e}")
        return False

    try:
        enhanced_recipes = pipeline.process_recipe_directory(data_dir=str(DATA_DIR))

        report_path = pipeline.save_summary_report(enhanced_recipes)

        logger.info(f"\n{'=' * 60}")
        logger.success("✓ All recipes test complete!")
        logger.info(f"Enhanced recipes: {len(enhanced_recipes)}")
        logger.info(f"Summary report saved to: {report_path}")

        return len(enhanced_recipes) > 0

    except Exception as e:
        logger.error(f"All recipes test failed with error: {e}")
        import traceback
        traceback.print_exc()
        return False


live_llm = pytest.mark.skipif(
    not (has_llm_key() and os.getenv("RUN_LIVE_LLM_TESTS") == "1"),
    reason="live LLM test: set RUN_LIVE_LLM_TESTS=1 and an LLM API key to run",
)


@live_llm
def test_single_recipe_live(tmp_path):
    assert run_single_recipe(output_dir=tmp_path)
    assert list(tmp_path.glob("enhanced_10813_*.json")), "no enhanced recipe file was written"


@live_llm
def test_all_recipes_live(tmp_path):
    assert run_all_recipes(output_dir=tmp_path)
    assert (tmp_path / "pipeline_summary_report.json").exists()


def test_run_single_recipe_fails_without_a_key(monkeypatch, tmp_path):
    """Without a key the helper must report failure, not pretend to pass."""
    for name in LLM_KEY_VARS:
        monkeypatch.delenv(name, raising=False)

    assert run_single_recipe(output_dir=tmp_path) is False
    assert run_all_recipes(output_dir=tmp_path) is False
    assert list(tmp_path.iterdir()) == []


def main():
    """Main test function with mode selection."""

    # Parse command line argument
    if len(sys.argv) < 2:
        logger.error("Usage: python test_pipeline.py [single|all]")
        logger.info("  single - Run single chocolate chip cookie recipe")
        logger.info("  all    - Run all recipes in data directory")
        sys.exit(1)

    mode = sys.argv[1].lower()

    if mode == "single":
        logger.info("Starting LLM Analysis Pipeline - Single Recipe Test")
        logger.info("=" * 60)
        success = run_single_recipe()

        logger.info("=" * 60)
        if success:
            logger.success("Single recipe test passed! ✓")
            logger.info("Check the 'data/enhanced/' directory for the enhanced recipe.")
        else:
            logger.error("Single recipe test failed! ✗")
            sys.exit(1)

    elif mode == "all":
        logger.info("Starting LLM Analysis Pipeline - All Recipes Validation")
        logger.info("=" * 60)
        success = run_all_recipes()

        logger.info("=" * 60)
        if success:
            logger.success("All recipes validation passed! ✓")
            logger.info("Check the 'data/enhanced/' directory for all enhanced recipes.")
            logger.info("Check 'data/enhanced/pipeline_summary_report.json' for detailed results.")
        else:
            logger.error("All recipes validation failed! ✗")
            sys.exit(1)

    else:
        logger.error(f"Unknown mode: {mode}")
        logger.error("Usage: python test_pipeline.py [single|all]")
        sys.exit(1)


if __name__ == "__main__":
    main()
