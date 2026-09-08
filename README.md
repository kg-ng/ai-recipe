# Recipe Enhancement Platform

Automatically enhances recipes by analyzing and applying community-tested modifications from AllRecipes.com. Uses LLM processing to extract meaningful recipe tweaks and apply them with full citation tracking.

## Installation

This project uses [`uv`](https://docs.astral.sh/uv/) for fast, reliable Python package management.

### Prerequisites

- Python 3.13+
- `uv` package manager

## Setup

```bash
# Install dependencies
uv venv
source .venv/bin/activate
uv pip sync pyproject.toml
```

### Environment Variables

Create a `.env` file in the project root:

```env
OPENAI_API_KEY=your-openai-api-key-here
```

The pipeline also supports free-tier alternatives to OpenAI (useful if you
don't have paid API credits) — set one of these instead, and the pipeline
auto-detects it in this priority order:

```env
GROQ_API_KEY=your-groq-api-key-here      # https://console.groq.com/keys (free, no card)
GEMINI_API_KEY=your-gemini-api-key-here  # https://aistudio.google.com/apikey (free, no card)
```

## Usage

### 1. Scrape Recipes (Optional - data already provided)

```bash
uv run python src/scraper_v2.py
```

### 2. Run Recipe Enhancement Pipeline

```bash
cd src

# Test single recipe (chocolate chip cookies)
uv run python test_pipeline.py single

# Process all recipes
uv run python test_pipeline.py all
```

## Output

### Enhanced Recipes

Enhanced recipes are saved in `data/enhanced/` at the repo root (the test script always writes there, regardless of your current directory):

- `enhanced_[recipe_id]_[recipe-name].json` - Individual enhanced recipes with modifications applied
- `pipeline_summary_report.json` - Summary of all processing results

### Latest Run Results

The pipeline was last run against all 6 scraped recipes (via the Groq free tier,
`openai/gpt-oss-20b`). 4 of 6 recipes had community tweaks available and were
enhanced; 2 had no `featured_tweaks` or `has_modification`-flagged reviews in
the scraped data, so they were correctly left unmodified (0 changes) rather
than the pipeline failing:

| Recipe | Modifications | Changes |
|---|---|---|
| Best Chocolate Chip Cookies | 5 | 5 |
| Creamy Sweet Potato With Ginger Soup | 10 | 6 |
| Spicy Apple Cake | 2 | 1 |
| Nikujaga (Japanese-Style Meat and Potatoes) | 1 | 1 |
| Spiced Purple Plum Jam | 0 | 0 (no source reviews available) |
| Mango Teriyaki Marinade | 0 | 0 (no source reviews available) |

### Data Structure

Original scraped recipes in `data/` directory contain reviews with `has_modification: true` flags. Enhanced recipes include:

```json
{
  "recipe_id": "10813_enhanced",
  "title": "Best Chocolate Chip Cookies (Community Enhanced)",
  "ingredients": ["1 cup butter", "1 additional egg yolk", ...],
  "modifications_applied": [
    {
      "source_review": {
        "text": "I added an extra egg yolk for chewier texture",
        "rating": 5
      },
      "modification_type": "addition",
      "reasoning": "Improves texture and chewiness",
      "changes_made": [...]
    }
  ],
  "enhancement_summary": {
    "total_changes": 1,
    "change_types": ["addition"],
    "expected_impact": "Chewier texture and improved consistency"
  },
  "rating": {"value": "4.6", "count": "19353"},
  "nutrition": {"calories": "146 kcal", "proteinContent": "2 g", ...},
  "url": "https://www.allrecipes.com/recipe/10813/best-chocolate-chip-cookies/",
  "author": "[{'@type': 'Person', 'name': 'Dora'}]",
  "categories": ["Dessert"],
  "prep_time": "PT20M",
  "cook_time": "PT10M",
  "total_time": "PT30M"
}
```

> `rating`, `nutrition`, `url`, `author`, `categories`, and `prep_time`/`cook_time`/`total_time`
> are carried over unchanged from the original scraped recipe (see
> [`docs/pipeline-fixes.md`](docs/pipeline-fixes.md#8-original-recipe-metadata-nutrition-rating-etc-was-silently-dropped-medium)
> for why these were previously dropped and how it was fixed).

## How It Works

The LLM Analysis Pipeline processes recipes in 3 steps:

1. **Tweak Extraction**: Sources modifications from the recipe's `featured_tweaks`
   (AllRecipes' own highest-voted, community-tested tweaks), falling back to any
   review flagged `has_modification` if a recipe has none scraped. All selected
   reviews for a recipe are sent through the LLM in a **single batched call**
   (cost optimization — avoids re-paying for recipe context tokens per review),
   which returns a **list** of discrete modifications tagged back to their source
   review — a single review describing several independent changes (e.g. "I
   added an egg and halved the sugar") is split into separate
   `addition`/`quantity_adjustment`/etc. objects instead of being merged into one.
   Falls back to one call per review only if the batch call fails outright.
2. **Recipe Modification**: Applies every extracted modification sequentially to
   the recipe using fuzzy string matching, falling back to a whole-line replace
   when the LLM's `find` text doesn't exactly match the recipe line, and skipping
   any edit that would produce no real change (no false-positive diffs).
3. **Enhanced Recipe Generation**: Creates an enhanced version with full citation
   tracking back to every source review that contributed a change. Recipes with no
   available community tweaks still produce an `EnhancedRecipe` (0 modifications,
   explicit message) instead of the pipeline silently failing.

Each run produces one enhanced recipe per original recipe — with potentially many
`modifications_applied` entries per recipe — with complete attribution showing
exactly what changed and why.

See `docs/pipeline-fixes.md` for the full list of correctness/scale bugs found in
the original implementation and how each was fixed.

## Development

```bash
# Add dependencies
uv add <package_name>

# Run the manual pipeline harness (needs OPENAI_API_KEY, calls the real LLM)
cd src && uv run python test_pipeline.py single   # or: all

# Run the automated unit test suite (mocked LLM, no API key required)
cd src && uv run pytest tests/ -v
```

## Agentic System (`.github/`)

This repo includes a Copilot CLI agent/skill setup used while diagnosing and
fixing the pipeline. See `.github/AGENTS_README.md` for the full breakdown:

- **Agents** (`.github/agents/`): `pipeline-planner` (entry point/orchestrator),
  `pipeline-qa-reviewer` (verifies multi-tweak extraction, scale, diff
  correctness), `pipeline-commit`, `pipeline-pr-preparer`, `rubber-duck` (generic
  logic reviewer).
- **Skills** (`.github/skills/`): reusable engineering practices — planning,
  TDD, code review, git workflow, debugging, docs/ADRs, security, doubt-driven
  development, shipping checklists.
- **Memory** (`.github/agents/pipeline-lessons.md`): an append-only log of every
  bug found in this pipeline, its root cause, and the fix applied. Agents read it
  before planning/reviewing so gaps aren't rediscovered — or silently
  reintroduced — across sessions. It doubles as a running changelog of the
  debugging work done in this repo.
