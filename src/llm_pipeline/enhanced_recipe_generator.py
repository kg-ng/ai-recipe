"""
Step 3: Enhanced Recipe Generation with Attribution

This module generates enhanced recipes with full citation tracking.
It combines modified recipes with attribution information to create
comprehensive enhanced recipe objects.
"""

from datetime import datetime
from typing import Any, Dict, List, Tuple

from loguru import logger

from .models import (
    ChangeRecord,
    EnhancedRecipe,
    EnhancementSummary,
    ModificationApplied,
    ModificationObject,
    Recipe,
    Review,
    SourceReview,
)


class EnhancedRecipeGenerator:
    """Generates enhanced recipes with full citation tracking and attribution."""

    def __init__(self, pipeline_version: str = "1.0.0"):
        """
        Initialize the Enhanced Recipe Generator.

        Args:
            pipeline_version: Version identifier for the pipeline
        """
        self.pipeline_version = pipeline_version
        logger.info(f"Initialized EnhancedRecipeGenerator v{pipeline_version}")

    def create_source_review(self, review: Review) -> SourceReview:
        """
        Convert a Review object to a SourceReview for attribution.

        Args:
            review: Original review object

        Returns:
            SourceReview with attribution information
        """
        return SourceReview(
            text=review.text, reviewer=review.username, rating=review.rating
        )

    def create_modification_applied(
        self,
        modification: ModificationObject,
        source_review: Review,
        change_records: List[ChangeRecord],
    ) -> ModificationApplied:
        """
        Create a ModificationApplied record for attribution.

        Args:
            modification: Original modification object
            source_review: Review that suggested this modification
            change_records: List of changes that were actually made

        Returns:
            ModificationApplied with full attribution
        """
        return ModificationApplied(
            source_review=self.create_source_review(source_review),
            modification_type=modification.modification_type,
            reasoning=modification.reasoning,
            changes_made=change_records,
        )

    def calculate_enhancement_summary(
        self, modifications_applied: List[ModificationApplied]
    ) -> EnhancementSummary:
        """
        Calculate summary statistics for all applied modifications.

        Args:
            modifications_applied: List of all modifications applied

        Returns:
            EnhancementSummary with aggregate statistics
        """
        total_changes = sum(len(mod.changes_made) for mod in modifications_applied)
        change_types = list(set(mod.modification_type for mod in modifications_applied))

        # Generate expected impact summary
        impact_descriptions = []
        for mod in modifications_applied:
            if mod.reasoning:
                impact_descriptions.append(mod.reasoning)

        expected_impact = "; ".join(impact_descriptions[:3])  # Limit to top 3
        if len(impact_descriptions) > 3:
            expected_impact += (
                f" (and {len(impact_descriptions) - 3} more improvements)"
            )

        if not modifications_applied:
            # Explicit, honest message for recipes with no community tweaks yet -
            # distinguishes "nothing to apply" from a pipeline failure.
            expected_impact = (
                "No community-tested modifications were available for this recipe."
            )

        return EnhancementSummary(
            total_changes=total_changes,
            change_types=change_types,
            expected_impact=expected_impact
            or "Community-validated recipe improvements",
        )

    def generate_enhanced_recipe(
        self,
        original_recipe: Recipe,
        modified_recipe: Recipe,
        applied_modifications: List[Tuple[ModificationObject, Review, List[ChangeRecord]]],
    ) -> EnhancedRecipe:
        """
        Generate a complete enhanced recipe with attribution.

        Args:
            original_recipe: Original unmodified recipe
            modified_recipe: Recipe with all modifications applied
            applied_modifications: List of (modification, source_review, change_records)
                tuples - one per discrete modification actually applied. May be an
                empty list if no community tweaks were available for this recipe;
                the resulting EnhancedRecipe will honestly reflect zero changes
                rather than the pipeline failing.

        Returns:
            Complete EnhancedRecipe with attribution
        """
        logger.info(f"Generating enhanced recipe for: {original_recipe.title}")

        # Create one ModificationApplied record per discrete modification
        modifications_applied = [
            self.create_modification_applied(modification, source_review, change_records)
            for modification, source_review, change_records in applied_modifications
        ]

        # Calculate enhancement summary
        enhancement_summary = self.calculate_enhancement_summary(modifications_applied)

        # Generate enhanced recipe ID and title
        enhanced_recipe_id = f"{original_recipe.recipe_id}_enhanced"
        enhanced_title = f"{original_recipe.title} (Community Enhanced)"

        # Create the enhanced recipe
        enhanced_recipe = EnhancedRecipe(
            recipe_id=enhanced_recipe_id,
            original_recipe_id=original_recipe.recipe_id,
            title=enhanced_title,
            ingredients=modified_recipe.ingredients,
            instructions=modified_recipe.instructions,
            modifications_applied=modifications_applied,
            enhancement_summary=enhancement_summary,
            description=original_recipe.description,
            servings=original_recipe.servings,
            # FIX: prep_time/cook_time/total_time used to be populated via
            # getattr(original_recipe, "prep_time", None) etc. - those
            # attribute names never existed on Recipe (which uses
            # preptime/cooktime/totaltime, matching the raw scraped JSON
            # keys), so the getattr() fallback silently returned None on
            # every run. Now reads the correct attribute names directly.
            prep_time=original_recipe.preptime,
            cook_time=original_recipe.cooktime,
            total_time=original_recipe.totaltime,
            # FIX: rating/nutrition/url/author/categories/featured_tweaks were
            # not passed through at all before - this metadata (and the raw
            # featured_tweaks used to audit which tips were considered vs.
            # applied) was silently dropped from every enhanced recipe. See
            # docs/pipeline-fixes.md #8/#9.
            rating=original_recipe.rating,
            nutrition=original_recipe.nutrition,
            url=original_recipe.url,
            author=original_recipe.author,
            categories=original_recipe.categories,
            featured_tweaks=original_recipe.featured_tweaks,
            created_at=datetime.now().isoformat(),
            pipeline_version=self.pipeline_version,
        )

        logger.info(
            f"Generated enhanced recipe with {enhancement_summary.total_changes} changes "
            f"from {len(modifications_applied)} modifications"
        )

        return enhanced_recipe

    def generate_comparison_data(
        self, original_recipe: Recipe, enhanced_recipe: EnhancedRecipe
    ) -> Dict[str, Any]:
        """
        Generate side-by-side comparison data for UI display.

        Args:
            original_recipe: Original recipe
            enhanced_recipe: Enhanced recipe

        Returns:
            Dictionary with comparison data
        """
        comparison = {
            "original": {
                "title": original_recipe.title,
                "ingredients": original_recipe.ingredients,
                "instructions": original_recipe.instructions,
                "servings": original_recipe.servings,
            },
            "enhanced": {
                "title": enhanced_recipe.title,
                "ingredients": enhanced_recipe.ingredients,
                "instructions": enhanced_recipe.instructions,
                "servings": enhanced_recipe.servings,
            },
            "changes": {
                "total_modifications": len(enhanced_recipe.modifications_applied),
                "total_changes": enhanced_recipe.enhancement_summary.total_changes,
                "change_types": enhanced_recipe.enhancement_summary.change_types,
                "expected_impact": enhanced_recipe.enhancement_summary.expected_impact,
            },
            "citations": [
                {
                    "reviewer": mod.source_review.reviewer,
                    "rating": mod.source_review.rating,
                    "modification_type": mod.modification_type,
                    "reasoning": mod.reasoning,
                    "changes": [
                        {
                            "type": change.type,
                            "from": change.from_text,
                            "to": change.to_text,
                            "operation": change.operation,
                        }
                        for change in mod.changes_made
                    ],
                }
                for mod in enhanced_recipe.modifications_applied
            ],
        }

        return comparison

    def save_enhanced_recipe(
        self, enhanced_recipe: EnhancedRecipe, output_path: str
    ) -> str:
        """
        Save enhanced recipe to JSON file.

        Args:
            enhanced_recipe: Enhanced recipe to save
            output_path: Path to save the file

        Returns:
            Path to the saved file
        """
        import json
        import os

        # Ensure output directory exists
        os.makedirs(os.path.dirname(output_path), exist_ok=True)

        # Convert to dict and save
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(enhanced_recipe.model_dump(), f, indent=2, ensure_ascii=False)

        logger.info(f"Saved enhanced recipe to: {output_path}")
        return output_path
