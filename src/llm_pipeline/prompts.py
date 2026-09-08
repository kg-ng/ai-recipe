"""
LLM prompts and examples for recipe modification extraction.

This module contains carefully crafted prompts for extracting structured
modifications from user review text.
"""

SYSTEM_PROMPT = """You are an expert recipe analyst. Your job is to extract structured recipe modifications from user reviews.

When a user shares their experience modifying a recipe, you need to:
1. Identify EVERY distinct, independently-describable change they made — a single
   review very often describes multiple discrete modifications (e.g. "I added an
   egg and halved the sugar" is TWO modifications: an addition AND a quantity
   adjustment; "I omitted the water and used 1 tsp of salt instead of 1/2 tsp" is
   a removal AND a quantity_adjustment).
2. Understand why each change was made
3. Convert each discrete modification into its own structured object with its own
   single category and its own edit operations

You must output valid JSON matching this schema:
{
    "modifications": [
        { <ModificationObject>, ... }
    ]
}

Each entry in "modifications" is exactly ONE ModificationObject and must cover
exactly ONE modification_type. Never merge two different kinds of changes (e.g. an
addition and a quantity adjustment) into a single object — split them into
separate entries in the array, each with its own edits. If a review only
describes one change, return an array with a single entry.

Categories (pick exactly one per modification object):
- "ingredient_substitution": Replacing one ingredient with another
- "quantity_adjustment": Changing amounts of existing ingredients
- "technique_change": Altering cooking method, temperature, time
- "addition": Adding new ingredients or steps
- "removal": Removing ingredients or steps

Edit operations:
- "replace": Find existing text and replace it
- "add_after": Add new text after finding target text
- "remove": Remove text that matches the find pattern

Be precise with text matching - use the exact text from the original recipe when possible."""

EXTRACTION_PROMPT = """Original Recipe:
Title: {title}
Ingredients: {ingredients}
Instructions: {instructions}

User Review: "{review_text}"

Extract EVERY discrete recipe modification from this review - do not stop after the
first one. The user may describe several independent changes in one sentence or
across several clauses.

Output a JSON object with this structure:
{{
    "modifications": [
        {{
            "modification_type": "quantity_adjustment|ingredient_substitution|technique_change|addition|removal",
            "reasoning": "Brief explanation of why this modification improves the recipe",
            "edits": [
                {{
                    "target": "ingredients|instructions",
                    "operation": "replace|add_after|remove",
                    "find": "exact text to find",
                    "replace": "replacement text (for replace operations)",
                    "add": "text to add (for add_after operations)"
                }}
            ]
        }}
    ]
}}

Focus on concrete changes the user actually made, not general suggestions. Split
compound changes into separate entries in "modifications" - one entry per
distinct modification_type."""

FEW_SHOT_EXAMPLES = [
    {
        "review": "I used a half cup of sugar and one-and-a-half cups of brown sugar instead of the recipe amounts. Made the cookies much more chewy and flavorful!",
        "ingredients": [
            "1 cup butter, softened",
            "1 cup white sugar",
            "1 cup packed brown sugar",
            "2 eggs",
        ],
        "expected_output": {
            "modifications": [
                {
                    "modification_type": "quantity_adjustment",
                    "reasoning": "Makes cookies more chewy and flavorful by increasing brown sugar ratio",
                    "edits": [
                        {
                            "target": "ingredients",
                            "operation": "replace",
                            "find": "1 cup white sugar",
                            "replace": "0.5 cup white sugar",
                        },
                        {
                            "target": "ingredients",
                            "operation": "replace",
                            "find": "1 cup packed brown sugar",
                            "replace": "1.5 cups packed brown sugar",
                        },
                    ],
                },
            ],
        },
    },
    {
        # Compound review: TWO independent modifications of DIFFERENT types.
        # Must produce two entries in "modifications", not one merged entry.
        "review": "I added a teaspoon of cream of tartar to the batter and omitted the water. The cookies retained their shape and didn't spread when baked.",
        "ingredients": [
            "1 teaspoon baking soda",
            "2 teaspoons hot water",
            "0.5 teaspoon salt",
        ],
        "expected_output": {
            "modifications": [
                {
                    "modification_type": "addition",
                    "reasoning": "Cream of tartar helps cookies retain shape during baking",
                    "edits": [
                        {
                            "target": "ingredients",
                            "operation": "add_after",
                            "find": "0.5 teaspoon salt",
                            "add": "1 teaspoon cream of tartar",
                        },
                    ],
                },
                {
                    "modification_type": "removal",
                    "reasoning": "Omitting the water prevents the cookies from spreading during baking",
                    "edits": [
                        {
                            "target": "ingredients",
                            "operation": "remove",
                            "find": "2 teaspoons hot water",
                        },
                    ],
                },
            ],
        },
    },
    {
        # Compound review: quantity_adjustment + removal, kept as two separate entries.
        "review": "I used 1 tsp of salt instead of 1/2 tsp and omitted the nuts. Much better flavor without being too salty.",
        "ingredients": ["0.5 teaspoon salt", "1 cup chopped walnuts"],
        "expected_output": {
            "modifications": [
                {
                    "modification_type": "quantity_adjustment",
                    "reasoning": "Doubling the salt improves flavor balance",
                    "edits": [
                        {
                            "target": "ingredients",
                            "operation": "replace",
                            "find": "0.5 teaspoon salt",
                            "replace": "1 teaspoon salt",
                        },
                    ],
                },
                {
                    "modification_type": "removal",
                    "reasoning": "Removing the walnuts avoids an overly salty/nutty flavor for those who dislike nuts",
                    "edits": [
                        {
                            "target": "ingredients",
                            "operation": "remove",
                            "find": "1 cup chopped walnuts",
                        },
                    ],
                },
            ],
        },
    },
    {
        "review": "I baked them at 375 degrees instead of 350 for about 8-9 minutes. They came out perfectly crispy on the edges.",
        "instructions": [
            "Preheat the oven to 350 degrees F (175 degrees C)",
            "Bake in the preheated oven until edges are nicely browned, about 10 minutes",
        ],
        "expected_output": {
            "modifications": [
                {
                    "modification_type": "technique_change",
                    "reasoning": "Higher temperature and shorter time creates crispier edges",
                    "edits": [
                        {
                            "target": "instructions",
                            "operation": "replace",
                            "find": "350 degrees F",
                            "replace": "375 degrees F",
                        },
                        {
                            "target": "instructions",
                            "operation": "replace",
                            "find": "about 10 minutes",
                            "replace": "about 8-9 minutes",
                        },
                    ],
                },
            ],
        },
    },
]


def build_few_shot_prompt(
    review_text: str, title: str, ingredients: list, instructions: list
) -> str:
    """Build a few-shot prompt with examples for better extraction accuracy."""

    examples_text = "\n\n".join(
        [
            f"Example {i + 1}:\n"
            f'Review: "{example["review"]}"\n'
            f"Output: {example['expected_output']}"
            for i, example in enumerate(
                FEW_SHOT_EXAMPLES[:2]
            )  # Use 2 most relevant examples
        ]
    )

    prompt = f"""{SYSTEM_PROMPT}

Here are some examples of how to extract modifications:

{examples_text}

Now extract from this review:

{
        EXTRACTION_PROMPT.format(
            title=title,
            ingredients=ingredients,
            instructions=instructions,
            review_text=review_text,
        )
    }"""

    return prompt


def build_simple_prompt(
    review_text: str, title: str, ingredients: list, instructions: list
) -> str:
    """
    Build a simple prompt without few-shot examples for faster/cheaper processing.

    NOTE: this must stay in sync with the "modifications": [...] list schema - it
    previously duplicated an outdated single-object schema independently of
    EXTRACTION_PROMPT, which meant the multi-modification fix never actually
    reached the real LLM call despite EXTRACTION_PROMPT itself being correct. Now
    delegates to EXTRACTION_PROMPT so there is exactly one place that defines this
    schema.
    """
    return f"""{SYSTEM_PROMPT}

{
        EXTRACTION_PROMPT.format(
            title=title,
            ingredients=ingredients,
            instructions=instructions,
            review_text=review_text,
        )
    }"""


def build_batch_prompt(
    reviews: list, title: str, ingredients: list, instructions: list
) -> str:
    """
    Build a single prompt that extracts modifications from MULTIPLE reviews in one
    LLM call (cost optimization - avoids paying for the recipe title/ingredients/
    instructions context tokens once per review when a recipe has several featured
    tweaks). Each returned modification must be tagged with `review_index`
    identifying which input review it came from.

    Args:
        reviews: list of review text strings, in order - the returned
            `review_index` refers to this order (0-based)
        title: recipe title
        ingredients: recipe ingredients list
        instructions: recipe instructions list
    """
    numbered_reviews = "\n".join(
        f'Review [{i}]: "{text}"' for i, text in enumerate(reviews)
    )

    return f"""{SYSTEM_PROMPT}

Original Recipe:
Title: {title}
Ingredients: {ingredients}
Instructions: {instructions}

You will be given SEVERAL reviews below, each with a numeric index in brackets.
Extract EVERY discrete recipe modification from EACH review - do not stop after
the first one per review, and do not skip any review. Tag every modification
with the `review_index` of the review it came from.

{numbered_reviews}

Output a JSON object with this structure:
{{
    "modifications": [
        {{
            "review_index": 0,
            "modification_type": "quantity_adjustment|ingredient_substitution|technique_change|addition|removal",
            "reasoning": "Brief explanation of why this modification improves the recipe",
            "edits": [
                {{
                    "target": "ingredients|instructions",
                    "operation": "replace|add_after|remove",
                    "find": "exact text to find",
                    "replace": "replacement text (for replace operations)",
                    "add": "text to add (for add_after operations)"
                }}
            ]
        }}
    ]
}}

Focus on concrete changes each reviewer actually made, not general suggestions.
Split compound changes into separate entries - one entry per distinct
modification_type, each correctly tagged with its own review_index."""
