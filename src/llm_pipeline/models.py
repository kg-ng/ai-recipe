"""
Pydantic data models for the LLM Analysis Pipeline.

These models define the structure for recipe modifications, enhanced recipes,
and all intermediate data formats used throughout the pipeline.
"""

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


class ModificationEdit(BaseModel):
    """Individual atomic edit operation for a recipe modification."""

    target: Literal["ingredients", "instructions"] = Field(
        description="Whether this edit applies to ingredients or instructions"
    )
    operation: Literal["replace", "add_after", "remove"] = Field(
        default="replace",
        description="Type of operation: replace text, add after target, or remove",
    )
    find: str = Field(description="Text to find in the recipe")
    replace: Optional[str] = Field(
        default=None, description="Replacement text (required for replace operations)"
    )
    add: Optional[str] = Field(
        default=None, description="Text to add (required for add_after operations)"
    )


class ModificationObject(BaseModel):
    """Structured modification parsed from a review."""

    modification_type: Literal[
        "ingredient_substitution",
        "quantity_adjustment",
        "technique_change",
        "addition",
        "removal",
    ] = Field(description="Category of modification")

    reasoning: str = Field(description="Why this modification improves the recipe")

    edits: List[ModificationEdit] = Field(description="List of atomic edits to apply")


class ModificationExtractionResult(BaseModel):
    """
    Wrapper for LLM extraction output. A single review can describe multiple
    discrete modifications (e.g. "I added an egg and halved the sugar" is an
    addition AND a quantity_adjustment). The LLM must return one ModificationObject
    per discrete, independently-describable change rather than merging everything
    under one modification_type.
    """

    modifications: List[ModificationObject] = Field(
        description="One entry per discrete modification found in the review. "
        "A compound review describing N independent changes must produce N entries."
    )


class BatchModificationObject(ModificationObject):
    """
    A ModificationObject tagged with which input review it came from. Used by the
    cost-optimized batch extraction path, which sends ALL of a recipe's reviews to
    the LLM in a single request (instead of one request per review) and asks it to
    label each returned modification with the index of the review it came from.
    """

    review_index: int = Field(
        description="0-based index into the batch's input review list identifying "
        "which review this modification was extracted from"
    )


class BatchModificationExtractionResult(BaseModel):
    """Wrapper for the multi-review batch extraction LLM output."""

    modifications: List[BatchModificationObject] = Field(
        description="One entry per discrete modification found across ALL input "
        "reviews, each tagged with its source review_index."
    )


class SourceReview(BaseModel):
    """Reference to the original review that suggested the modification."""

    text: str = Field(description="Full text of the original review")
    reviewer: Optional[str] = Field(description="Username of the reviewer")
    rating: Optional[int] = Field(description="Star rating given by reviewer")


class ChangeRecord(BaseModel):
    """Record of a specific change made to the recipe."""

    type: Literal["ingredient", "instruction"] = Field(
        description="Type of element that was changed"
    )
    from_text: str = Field(description="Original text before modification")
    to_text: str = Field(description="New text after modification")
    operation: Literal["replace", "add", "remove"] = Field(
        description="Type of operation performed"
    )


class ModificationApplied(BaseModel):
    """Full record of a modification that was applied to a recipe."""

    source_review: SourceReview = Field(
        description="Review that suggested this modification"
    )
    modification_type: str = Field(description="Category of modification")
    reasoning: str = Field(description="Why this modification was applied")
    changes_made: List[ChangeRecord] = Field(
        description="Detailed list of changes made"
    )


class EnhancementSummary(BaseModel):
    """Summary of all modifications applied to a recipe."""

    total_changes: int = Field(description="Total number of changes made")
    change_types: List[str] = Field(description="Types of modifications applied")
    expected_impact: str = Field(
        description="Expected improvement from these modifications"
    )


class EnhancedRecipe(BaseModel):
    """Recipe with community modifications applied and full attribution."""

    recipe_id: str = Field(description="Enhanced recipe ID")
    original_recipe_id: str = Field(description="ID of the original recipe")
    title: str = Field(description="Enhanced recipe title")

    # Enhanced recipe content
    ingredients: List[str] = Field(description="Modified ingredients list")
    instructions: List[str] = Field(description="Modified instructions list")

    # Attribution and tracking
    modifications_applied: List[ModificationApplied] = Field(
        description="Full record of all modifications applied"
    )
    enhancement_summary: EnhancementSummary = Field(
        description="Summary of all enhancements"
    )

    # Optional metadata
    description: Optional[str] = Field(description="Enhanced recipe description")
    servings: Optional[str] = Field(description="Number of servings")
    prep_time: Optional[str] = Field(description="Preparation time")
    cook_time: Optional[str] = Field(description="Cooking time")
    total_time: Optional[str] = Field(description="Total time")
    rating: Optional[Dict[str, Any]] = Field(
        default=None, description="Original recipe rating (value/count)"
    )
    nutrition: Optional[Dict[str, Any]] = Field(
        default=None, description="Nutrition facts carried over from the original recipe"
    )
    url: Optional[str] = Field(default=None, description="Source URL of the original recipe")
    author: Optional[str] = Field(default=None, description="Original recipe author")
    categories: Optional[List[str]] = Field(
        default=None, description="Recipe categories (e.g. Dessert)"
    )
    featured_tweaks: Optional[List[Dict[str, Any]]] = Field(
        default=None,
        description="Raw featured_tweaks as scraped from the original recipe - "
        "the full set of highest-voted, community-tested tweaks that were "
        "considered as modification sources. Preserved verbatim (regardless of "
        "whether each one ended up producing an entry in modifications_applied) "
        "so consumers can audit which featured tweaks were considered vs. "
        "actually applied.",
    )

    # Generation metadata
    created_at: str = Field(description="When this enhanced recipe was created")
    pipeline_version: str = Field(
        default="1.0.0", description="Version of the pipeline that created this"
    )


class Recipe(BaseModel):
    """Base recipe model for input data."""

    recipe_id: str
    title: str
    ingredients: List[str]
    instructions: List[str]
    description: Optional[str] = None
    servings: Optional[str] = None
    rating: Optional[Dict[str, Any]] = None
    preptime: Optional[str] = None
    cooktime: Optional[str] = None
    totaltime: Optional[str] = None
    nutrition: Optional[Dict[str, Any]] = None
    url: Optional[str] = None
    author: Optional[str] = None
    categories: Optional[List[str]] = None
    featured_tweaks: Optional[List[Dict[str, Any]]] = None
    # Include other fields as needed


class Review(BaseModel):
    """Review model for input data."""

    text: str
    rating: Optional[int] = None
    username: Optional[str] = None
    has_modification: bool = False
    is_featured: bool = False
