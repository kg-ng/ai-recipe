"""
Step 1: Tweak Extraction & Parsing

This module extracts structured modifications from review text using LLM processing.
It converts natural language descriptions of recipe changes into structured
ModificationObject instances.

A single review often describes multiple independent modifications (e.g. "I added
an egg and halved the sugar"). extract_modifications() always returns a LIST of
ModificationObject instances per review so compound changes aren't silently
truncated to a single merged (and often mis-typed) modification.
"""

import json
import os
from typing import List, Optional, Tuple

from loguru import logger
from openai import OpenAI
from pydantic import ValidationError

from .models import (
    BatchModificationExtractionResult,
    ModificationExtractionResult,
    ModificationObject,
    Recipe,
    Review,
)
from .prompts import build_batch_prompt, build_simple_prompt


class TweakExtractor:
    """Extracts structured modifications from review text using LLM processing."""

    def __init__(self, api_key: Optional[str] = None, model: str = "gpt-3.5-turbo"):
        """
        Initialize the TweakExtractor.

        Args:
            api_key: OpenAI API key (defaults to OPENAI_API_KEY env var)
            model: OpenAI model to use for extraction
        """
        self.client = OpenAI(api_key=api_key or os.getenv("OPENAI_API_KEY"))
        self.model = model
        logger.info(f"Initialized TweakExtractor with model: {model}")

    def extract_modifications(
        self,
        review: Review,
        recipe: Recipe,
        max_retries: int = 2,
    ) -> List[ModificationObject]:
        """
        Extract ALL structured modifications described in a single review.

        A review may describe several discrete, independently-describable changes
        (different modification_types or several edits of the same type). This
        returns one ModificationObject per discrete change - never merges two
        different kinds of changes into one object.

        Args:
            review: Review object containing modification text
            recipe: Original recipe being modified
            max_retries: Number of retry attempts if parsing fails

        Returns:
            List of ModificationObject instances (empty list if extraction failed
            or the review had nothing to extract).
        """
        if not review.has_modification:
            logger.warning("Review has no modification flag set")
            return []

        # Build the prompt - use simple prompt to avoid format string issues
        prompt = build_simple_prompt(
            review.text, recipe.title, recipe.ingredients, recipe.instructions
        )

        logger.debug(
            "Extracting modifications from review: {}...".format(review.text[:100])
        )

        raw_output = None
        extraction_data = None
        for attempt in range(max_retries + 1):
            try:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=[{"role": "user", "content": prompt}],
                    response_format={"type": "json_object"},
                    temperature=0.1,  # Low temperature for consistent extractions
                    max_tokens=1500,
                )

                raw_output = response.choices[0].message.content
                logger.debug(f"LLM raw output: {raw_output}")

                # Check if we got a response
                if not raw_output:
                    logger.warning(f"Attempt {attempt + 1}: Empty response from LLM")
                    continue

                # Parse and validate the JSON response
                extraction_data = json.loads(raw_output)

                # Backward/leniency: accept either the new {"modifications": [...]}
                # shape or a single bare ModificationObject dict (in case the model
                # ignores instructions and returns just one object).
                if "modifications" not in extraction_data and "modification_type" in extraction_data:
                    extraction_data = {"modifications": [extraction_data]}

                result = ModificationExtractionResult(**extraction_data)

                logger.info(
                    f"Successfully extracted {len(result.modifications)} discrete "
                    f"modification(s) from review "
                    f"({', '.join(m.modification_type for m in result.modifications)})"
                )
                return result.modifications

            except json.JSONDecodeError as e:
                logger.warning(f"Attempt {attempt + 1}: Failed to parse JSON: {e}")
                if attempt == max_retries:
                    logger.error(f"Max retries reached. Raw output: {raw_output}")

            except ValidationError as e:
                logger.warning(f"Attempt {attempt + 1}: Validation error: {e}")
                if attempt == max_retries:
                    logger.error(
                        f"Max retries reached. Invalid data: {extraction_data}"
                    )

            except Exception as e:
                logger.error(f"Attempt {attempt + 1}: Unexpected error: {e}")
                if attempt == max_retries:
                    return []

        return []

    def extract_modifications_batch(
        self,
        reviews: List[Review],
        recipe: Recipe,
        max_retries: int = 2,
    ) -> Optional[List[Tuple[ModificationObject, Review]]]:
        """
        Cost-optimized extraction: send ALL reviews to the LLM in a SINGLE request
        instead of one request per review. This avoids re-paying for the recipe
        title/ingredients/instructions context tokens once per review (the
        dominant cost when a recipe has several featured tweaks), and cuts fixed
        per-request overhead from N calls down to 1 per recipe.

        Args:
            reviews: Reviews to extract from (already filtered by caller)
            recipe: Original recipe being modified
            max_retries: Number of retry attempts if parsing fails

        Returns:
            List of (ModificationObject, source_review) tuples if the batch call
            succeeded, or None if it failed entirely (caller should fall back to
            per-review extraction rather than silently returning nothing).
        """
        if not reviews:
            return []

        prompt = build_batch_prompt(
            [r.text for r in reviews],
            recipe.title,
            recipe.ingredients,
            recipe.instructions,
        )

        raw_output = None
        extraction_data = None
        for attempt in range(max_retries + 1):
            try:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=[{"role": "user", "content": prompt}],
                    response_format={"type": "json_object"},
                    temperature=0.1,
                    # Scale token budget with review count - a single-review
                    # budget would truncate output when batching many reviews.
                    max_tokens=min(4000, 800 + 400 * len(reviews)),
                )

                raw_output = response.choices[0].message.content
                logger.debug(f"Batch LLM raw output: {raw_output}")

                if not raw_output:
                    logger.warning(f"Attempt {attempt + 1}: Empty response from LLM")
                    continue

                extraction_data = json.loads(raw_output)
                result = BatchModificationExtractionResult(**extraction_data)

                results: List[Tuple[ModificationObject, Review]] = []
                for batch_mod in result.modifications:
                    if not (0 <= batch_mod.review_index < len(reviews)):
                        logger.warning(
                            f"Batch result referenced out-of-range review_index "
                            f"{batch_mod.review_index} (only {len(reviews)} "
                            "review(s) sent) - dropping this modification"
                        )
                        continue
                    source_review = reviews[batch_mod.review_index]
                    modification = ModificationObject(
                        modification_type=batch_mod.modification_type,
                        reasoning=batch_mod.reasoning,
                        edits=batch_mod.edits,
                    )
                    results.append((modification, source_review))

                logger.info(
                    f"Batch-extracted {len(results)} modification(s) from "
                    f"{len(reviews)} review(s) in a single LLM call"
                )
                return results

            except json.JSONDecodeError as e:
                logger.warning(f"Attempt {attempt + 1}: Failed to parse batch JSON: {e}")
                if attempt == max_retries:
                    logger.error(f"Max retries reached. Raw output: {raw_output}")

            except ValidationError as e:
                logger.warning(f"Attempt {attempt + 1}: Batch validation error: {e}")
                if attempt == max_retries:
                    logger.error(f"Max retries reached. Invalid data: {extraction_data}")

            except Exception as e:
                logger.error(f"Attempt {attempt + 1}: Unexpected batch error: {e}")
                if attempt == max_retries:
                    return None

        return None

    def extract_modifications_from_reviews(
        self, reviews: List[Review], recipe: Recipe
    ) -> List[Tuple[ModificationObject, Review]]:
        """
        Extract modifications from ALL provided reviews (not just one random pick).

        Callers are expected to pass in the reviews they want considered - e.g. the
        recipe's `featured_tweaks` (the highest-voted, community-tested
        modifications) rather than the full unfiltered review list. Each review can
        contribute multiple (modification, source_review) pairs since a single
        review may describe several discrete changes.

        Cost optimization: tries a single batched LLM call covering all reviews
        first (see `extract_modifications_batch`). Only falls back to one LLM call
        per review if the batch call fails outright (e.g. malformed/truncated
        response) - this keeps the common case cheap while still being resilient.

        Args:
            reviews: Reviews to extract from (already filtered/prioritized by caller)
            recipe: Original recipe being modified

        Returns:
            Flat list of (ModificationObject, source_review) tuples, in review order.
        """
        modification_reviews = [r for r in reviews if r.has_modification]

        if not modification_reviews:
            logger.warning("No reviews with modifications found")
            return []

        batch_results = self.extract_modifications_batch(modification_reviews, recipe)
        if batch_results is not None:
            logger.info(
                f"Extracted {len(batch_results)} total modification(s) from "
                f"{len(modification_reviews)} review(s) via 1 batched LLM call"
            )
            return batch_results

        logger.warning(
            "Batch extraction failed - falling back to one LLM call per review "
            "(higher cost, but more resilient)"
        )
        results: List[Tuple[ModificationObject, Review]] = []
        for review in modification_reviews:
            logger.info(f"Extracting from review: {review.text[:100]}...")
            modifications = self.extract_modifications(review, recipe)
            if not modifications:
                logger.warning(f"No modifications extracted from review: {review.text[:60]}...")
                continue
            for modification in modifications:
                results.append((modification, review))

        logger.info(
            f"Extracted {len(results)} total modification(s) from "
            f"{len(modification_reviews)} review(s) via per-review fallback"
        )
        return results

    def test_extraction(
        self, review_text: str, recipe_data: dict
    ) -> List[ModificationObject]:
        """
        Test extraction with raw text and recipe data.

        Args:
            review_text: Raw review text
            recipe_data: Raw recipe dictionary

        Returns:
            List of ModificationObject instances extracted from the review
        """
        review = Review(text=review_text, has_modification=True)
        recipe = Recipe(
            recipe_id=recipe_data.get("recipe_id", "test"),
            title=recipe_data.get("title", "Test Recipe"),
            ingredients=recipe_data.get("ingredients", []),
            instructions=recipe_data.get("instructions", []),
        )

        return self.extract_modifications(review, recipe)
