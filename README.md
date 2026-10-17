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

The scraper identifies itself (`SCRAPER_USER_AGENT` overrides it), times out after 15 seconds, and waits
1.5 seconds between recipes (`SCRAPE_DELAY_SECONDS`). Check the site's terms and `robots.txt` before running it.

> **About the data in `data/`:** it is recipe and review text scraped from AllRecipes.com for a coursework
> project, kept here only so the pipeline and the evals can be reproduced. It is not licensed for reuse or
> redistribution, and the authors of the reviews retain their rights. If you own content here and want it
> removed, open an issue. For anything beyond coursework, replace it with data you have the right to use;
> the golden set in `src/evals/` points at reviews by index and a text prefix, so it would need relabeling.

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

# Run the manual pipeline harness (needs an LLM key, calls the real LLM)
cd src && uv run python test_pipeline.py single   # or: all

# Run the automated test suite (no API key required; the two live-LLM tests are skipped)
cd src && uv run pytest -v

# Run the live-LLM tests too. They write to a temp dir and call a real (possibly paid) provider.
cd src && RUN_LIVE_LLM_TESTS=1 uv run pytest test_pipeline.py -v
```

## Evaluation

The pipeline has three stages: choose which reviews to use, have an LLM turn each review into
structured edits, then apply those edits to the recipe. `src/evals/` measures each stage
against hand-labeled data, so a regression can be traced to the stage that caused it.

```bash
cd src
python -m evals.run_eval                           # offline: keyword baseline + all offline metrics
python -m evals.run_eval --predictor llm-pipeline  # the real pipeline path (needs an LLM key)
python -m evals.run_eval --predictor llm-model     # the model alone, every review, no selection gate
python -m evals.run_eval --save preds.json         # keep predictions; re-score later with --predictions
```

| Data | What it is |
|---|---|
| `src/evals/golden_extraction.json` | Golden set. All 19 reviews of the 4 recipes that have reviews, hand-labeled: 31 scored tweaks (type + terms that must appear), 2 marked too vague to score, and 5 reviews with no tweak at all (to catch false alarms). |
| `src/evals/golden_modifier.json` | 15 edits on real recipe lines, each with the result a careful cook would want. |

| Metric | Stage | Needs a key? |
|---|---|---|
| Recall ceiling | Review selection: the share of labeled tweaks that reach the LLM at all | no |
| Precision / recall / F1 (strict and lenient), recall by type, false-alarm rate | LLM extraction vs. the labels | yes, or the baseline |
| Edit grounding | Does each extracted `find` point at a real recipe line? | yes |
| Exact match, silent wrong edits, edits not applied | `RecipeModifier` | no |

**Results measured on this repo** (keyword baseline, no LLM, 2026-10-17):

| | Result |
|---|---|
| Recall ceiling | **90.3%**: 3 of 31 tweaks never reach the LLM. The scraper's `has_modification` flag misses real tweaks, e.g. "I threw in carrots" in the Nikujaga recipe. |
| Keyword baseline, strict | precision 67.7%, recall 67.7%, F1 67.7% (the floor an LLM should beat) |
| `RecipeModifier` before the fix | 9 of 13 cases correct, **2 silent wrong edits**, 2 edits not applied |
| `RecipeModifier` after the fix | 15 of 15 cases correct, 0 silent wrong edits |

The modifier failures were real: fuzzy-only matching missed the exact phrase `about 10 minutes` that the
prompt's own example asks the LLM to use, edited the batter's shortening when a frosting line also matched,
and turned `packed brown sugar` into `1 cup 1.5 cups packed brown sugar`.

**What these numbers do not show.**
- **No LLM result is reported.** No API key was available when this was written. Run `--predictor llm-pipeline`
  to get one; `--save` keeps the predictions so the score can be reproduced.
- **The golden set is small and labeled by one person** (19 reviews, 4 recipes). Treat differences of a few points as noise.
- **The modifier fix was written after seeing its failing cases**, so 15/15 is partly tuned to this set.
  Two more cases (`replace_bare_name_with_quantity`, `add_after_ambiguous_anchor`) were added after the fix to probe
  its edges and passed, but they were never run against the old modifier, so they are not part of the before/after numbers.
- **The baseline's cue words were written after reading these reviews.** It is a floor, not an independent benchmark.
- **Matching is term-based.** A prediction counts if the type is right and a labeled term appears in it, so a
  correct edit with unexpected wording is scored as a miss.

The golden set is tied to the committed `data/` files by a text prefix per review, so a re-scrape that
changes a review fails `test_golden_set_matches_committed_data` instead of silently mislabeling it.

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
