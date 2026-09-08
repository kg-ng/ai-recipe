"""
LLM Analysis Pipeline - Main Orchestrator

This module coordinates the complete 3-step pipeline:
1. Extract modifications from reviews
2. Apply modifications to recipes
3. Generate enhanced recipes with attribution

Processes recipe data from scraped JSON files and outputs enhanced recipes.
"""

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from loguru import logger

from .enhanced_recipe_generator import EnhancedRecipeGenerator
from .models import EnhancedRecipe, Recipe, Review
from .recipe_modifier import RecipeModifier
from .tweak_extractor import TweakExtractor


class LLMAnalysisPipeline:
    """Complete pipeline for analyzing recipes and generating enhanced versions."""

    def __init__(
        self,
        openai_api_key: Optional[str] = None,
        output_dir: str = "data/enhanced",
        pipeline_version: str = "1.0.0",
    ):
        """
        Initialize the complete LLM Analysis Pipeline.

        Args:
            openai_api_key: OpenAI API key (loads from env if not provided)
            output_dir: Directory to save enhanced recipes
            pipeline_version: Version identifier for tracking
        """
        # Load environment variables
        load_dotenv()

        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Initialize pipeline components
        self.tweak_extractor = TweakExtractor(api_key=openai_api_key)
        self.recipe_modifier = RecipeModifier()
        self.enhanced_generator = EnhancedRecipeGenerator(
            pipeline_version=pipeline_version
        )

        logger.info(f"Initialized LLM Analysis Pipeline v{pipeline_version}")
        logger.info(f"Output directory: {self.output_dir}")

    def load_recipe_data(self, file_path: str) -> Dict[str, Any]:
        """
        Load recipe data from JSON file.

        Args:
            file_path: Path to recipe JSON file

        Returns:
            Recipe data dictionary
        """
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def parse_recipe_data(self, recipe_data: Dict[str, Any]) -> Recipe:
        """
        Parse raw recipe data into Recipe object.

        Args:
            recipe_data: Raw recipe data from JSON

        Returns:
            Recipe object
        """
        return Recipe(
            recipe_id=recipe_data.get("recipe_id", "unknown"),
            title=recipe_data.get("title", "Unknown Recipe"),
            ingredients=recipe_data.get("ingredients", []),
            instructions=recipe_data.get("instructions", []),
            description=recipe_data.get("description"),
            servings=recipe_data.get("servings"),
            rating=recipe_data.get("rating"),
        )

    def parse_reviews_data(self, recipe_data: Dict[str, Any]) -> List[Review]:
        """
        Parse raw review data into Review objects.

        Args:
            recipe_data: Raw recipe data containing reviews

        Returns:
            List of Review objects
        """
        reviews = []
        raw_reviews = recipe_data.get("reviews", [])

        for review_data in raw_reviews:
            if review_data.get("text"):
                review = Review(
                    text=review_data["text"],
                    rating=review_data.get("rating"),
                    username=review_data.get("username"),
                    has_modification=review_data.get("has_modification", False),
                    is_featured=review_data.get("is_featured", False),
                )
                reviews.append(review)

        return reviews

    def parse_featured_tweaks(self, recipe_data: Dict[str, Any]) -> List[Review]:
        """
        Parse the recipe's `featured_tweaks` - the highest-voted, community-tested
        modifications AllRecipes surfaces (the actual "Featured Tweaks" this
        product is meant to apply). This is the primary source of modifications;
        the generic `reviews` list is a superset that includes non-featured/non-
        modification reviews not meant to drive edits.

        Args:
            recipe_data: Raw recipe data containing a `featured_tweaks` list

        Returns:
            List of Review objects built from featured_tweaks
        """
        reviews = []
        for review_data in recipe_data.get("featured_tweaks", []):
            if review_data.get("text"):
                reviews.append(
                    Review(
                        text=review_data["text"],
                        rating=review_data.get("rating"),
                        username=review_data.get("username"),
                        has_modification=review_data.get("has_modification", True),
                        is_featured=review_data.get("is_featured", True),
                    )
                )
        return reviews

    def select_source_reviews(self, recipe_data: Dict[str, Any]) -> List[Review]:
        """
        Select which reviews to extract modifications from.

        Prefers `featured_tweaks` (the highest-voted community-tested tweaks -
        the actual product premise). Falls back to any review flagged
        `has_modification` when a recipe has no scraped featured tweaks, so the
        pipeline still degrades gracefully instead of silently doing nothing.

        Args:
            recipe_data: Raw recipe data

        Returns:
            List of Review objects to run extraction against (may be empty)
        """
        featured = self.parse_featured_tweaks(recipe_data)
        if featured:
            logger.info(f"Using {len(featured)} featured_tweaks as modification source")
            return featured

        all_reviews = self.parse_reviews_data(recipe_data)
        fallback = [r for r in all_reviews if r.has_modification]
        if fallback:
            logger.warning(
                "No featured_tweaks found for this recipe - falling back to "
                f"{len(fallback)} review(s) flagged has_modification"
            )
        else:
            logger.warning(
                "No featured_tweaks and no has_modification reviews found - "
                "this recipe has no community tweaks to apply"
            )
        return fallback

    def process_single_recipe(
        self, recipe_file: str, save_output: bool = True
    ) -> Optional[EnhancedRecipe]:
        """
        Process a single recipe through the complete pipeline.

        Args:
            recipe_file: Path to recipe JSON file
            save_output: Whether to save the enhanced recipe

        Returns:
            EnhancedRecipe if successful, None otherwise
        """
        try:
            logger.info(f"Processing recipe file: {recipe_file}")

            # Step 0: Load and parse data
            recipe_data = self.load_recipe_data(recipe_file)
            recipe = self.parse_recipe_data(recipe_data)
            all_reviews = self.parse_reviews_data(recipe_data)
            source_reviews = self.select_source_reviews(recipe_data)

            logger.info(f"Loaded recipe: {recipe.title}")
            logger.info(
                f"Found {len(all_reviews)} reviews, {len(source_reviews)} selected "
                "as modification sources (featured_tweaks preferred, has_modification fallback)"
            )

            applied_modifications: List[Any] = []
            modified_recipe = recipe

            if not source_reviews:
                # No community tweaks scraped for this recipe. Degrade gracefully:
                # still produce an EnhancedRecipe (0 modifications, honest summary)
                # instead of returning None and silently dropping the recipe from
                # `data/enhanced/` - this is a valid product state, not a failure.
                logger.warning(
                    "No community tweaks available for this recipe - "
                    "producing enhanced recipe with zero modifications"
                )
            else:
                # Step 1: Extract ALL discrete modifications from ALL source reviews
                logger.info(
                    f"Step 1: Extracting modifications from {len(source_reviews)} "
                    "source review(s)..."
                )
                extracted = self.tweak_extractor.extract_modifications_from_reviews(
                    source_reviews, recipe
                )

                if not extracted:
                    logger.warning(
                        "No modifications could be extracted from any source review"
                    )
                else:
                    logger.info(
                        f"Step 2: Applying {len(extracted)} modification(s) to recipe..."
                    )
                    current_recipe = recipe
                    for modification, source_review in extracted:
                        current_recipe, change_records = (
                            self.recipe_modifier.apply_modification(
                                current_recipe, modification
                            )
                        )
                        applied_modifications.append(
                            (modification, source_review, change_records)
                        )
                    modified_recipe = current_recipe

                    logger.info(
                        f"Applied {len(applied_modifications)} modification(s): "
                        f"{sum(len(c) for _, _, c in applied_modifications)} total changes made"
                    )

            # Step 3: Generate enhanced recipe with attribution
            logger.info("Step 3: Generating enhanced recipe with attribution...")

            enhanced_recipe = self.enhanced_generator.generate_enhanced_recipe(
                recipe, modified_recipe, applied_modifications
            )

            logger.info(f"Generated enhanced recipe: {enhanced_recipe.title}")

            # Save output
            if save_output:
                output_filename = f"enhanced_{recipe.recipe_id}_{recipe.title.lower().replace(' ', '-')[:30]}.json"
                output_path = self.output_dir / output_filename
                self.enhanced_generator.save_enhanced_recipe(
                    enhanced_recipe, str(output_path)
                )

            return enhanced_recipe

        except Exception as e:
            logger.error(f"Failed to process recipe {recipe_file}: {e}")
            import traceback

            traceback.print_exc()
            return None

    def process_recipe_directory(self, data_dir: str = "data") -> List[EnhancedRecipe]:
        """
        Process all recipe files in a directory.

        Args:
            data_dir: Directory containing recipe JSON files

        Returns:
            List of successfully processed EnhancedRecipe objects
        """
        data_path = Path(data_dir)
        recipe_files = list(data_path.glob("recipe_*.json"))

        logger.info(f"Found {len(recipe_files)} recipe files to process")

        enhanced_recipes = []
        for recipe_file in recipe_files:
            logger.info(f"\n{'=' * 60}")
            enhanced_recipe = self.process_single_recipe(str(recipe_file))

            if enhanced_recipe:
                enhanced_recipes.append(enhanced_recipe)
                logger.info(f"✓ Successfully processed: {enhanced_recipe.title}")
            else:
                logger.warning(f"✗ Failed to process: {recipe_file.name}")

        logger.info(f"\n{'=' * 60}")
        logger.info(
            f"Pipeline complete: {len(enhanced_recipes)}/{len(recipe_files)} recipes successfully enhanced"
        )

        return enhanced_recipes

    def generate_summary_report(
        self, enhanced_recipes: List[EnhancedRecipe]
    ) -> Dict[str, Any]:
        """
        Generate a summary report of pipeline results.

        Args:
            enhanced_recipes: List of enhanced recipes

        Returns:
            Summary report dictionary
        """
        if not enhanced_recipes:
            return {"status": "no_recipes_processed"}

        total_modifications = sum(
            len(recipe.modifications_applied) for recipe in enhanced_recipes
        )
        total_changes = sum(
            recipe.enhancement_summary.total_changes for recipe in enhanced_recipes
        )

        change_type_counts = {}
        for recipe in enhanced_recipes:
            for change_type in recipe.enhancement_summary.change_types:
                change_type_counts[change_type] = (
                    change_type_counts.get(change_type, 0) + 1
                )

        report = {
            "pipeline_summary": {
                "recipes_processed": len(enhanced_recipes),
                "total_modifications_applied": total_modifications,
                "total_changes_made": total_changes,
                "change_type_distribution": change_type_counts,
            },
            "enhanced_recipes": [
                {
                    "recipe_id": recipe.recipe_id,
                    "title": recipe.title,
                    "modifications_count": len(recipe.modifications_applied),
                    "changes_count": recipe.enhancement_summary.total_changes,
                    "change_types": recipe.enhancement_summary.change_types,
                }
                for recipe in enhanced_recipes
            ],
        }

        return report

    def save_summary_report(
        self, enhanced_recipes: List[EnhancedRecipe], output_path: Optional[str] = None
    ) -> str:
        """
        Save pipeline summary report to JSON file.

        Args:
            enhanced_recipes: List of enhanced recipes
            output_path: Path to save report (auto-generated if None)

        Returns:
            Path to saved report
        """
        if output_path is None:
            output_path = str(self.output_dir / "pipeline_summary_report.json")

        report = self.generate_summary_report(enhanced_recipes)

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)

        logger.info(f"Saved pipeline summary report to: {output_path}")
        return output_path
