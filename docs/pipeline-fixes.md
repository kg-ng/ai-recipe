# Pipeline Diagnosis & Fixes

This document covers: what was wrong with the inherited `src/llm_pipeline/`
implementation, why, how each issue was fixed, and what's intentionally left as a
known limitation given the assignment's 4-hour scope.

## Assumptions

- The scraped data in `data/*.json` (5 recipes) is representative but not
  exhaustive — the goal was to find and fix assumptions that only hold for these
  5 recipes, not to hand-tune the pipeline to pass on exactly these 5.
- Initial validation used **mocked LLM responses** built from the *actual* review
  text in the sample data (see `src/tests/`), since no `OPENAI_API_KEY` was
  available from the primary working environment (its network blocks calls to
  `api.openai.com` at the proxy level — confirmed directly, not just inferred).
  A real key was later run against the live OpenAI API from an unblocked network,
  which regenerated `data/enhanced/enhanced_10813_best-chocolate-chip-cookies.json`
  and confirmed the fix live (see "Live verification" below) — the mocked tests
  remain as fast, repeatable regression coverage.
- "Featured Tweaks" (per the assignment brief) = the `featured_tweaks` field
  already present in the scraped JSON (`is_featured: true`), which is a subset of
  `reviews`. This looks exactly like AllRecipes' own highest-voted/curated tweaks
  section referenced in the assignment.

## Problem Analysis & Fixes

### 1. Compound reviews were silently truncated to one modification (HIGH)

**Found:** `ModificationObject` had a single `modification_type` field. A review
like *"I used a half cup of sugar and one-and-a-half cups of brown sugar... I
omitted the water... I added a teaspoon of cream of tartar... I refrigerated the
batter..."* (an actual review in the sample data, 4 discrete tweaks) could only
ever be captured as **one** category — the rest were dropped with no warning, no
error, and no trace in the output.

Worse: the original few-shot prompt examples *modeled this bug* — e.g. an example
review describing "added cream of tartar" (an addition) AND "omitted water" (a
removal) was itself force-labeled as a single `"addition"`.

**Root cause:** schema and prompt were designed around a "one review → one tweak"
assumption that doesn't hold for real review text, which routinely describes
several independent changes in one sentence or paragraph.

**Fix:**
- Added `ModificationExtractionResult(modifications: List[ModificationObject])` in
  `models.py`.
- Rewrote `SYSTEM_PROMPT`/`EXTRACTION_PROMPT` in `prompts.py` to require the model
  to return **one array entry per discrete, independently-describable change**,
  never merging two modification types into one object.
- Rewrote the few-shot examples to correctly split their own compound reviews
  into multiple entries (previously they modeled the bug).
- `TweakExtractor.extract_modifications()` now returns `List[ModificationObject]`
  per review (renamed from `extract_modification` → singular result).
- Leniency: if the model ignores instructions and returns a bare single object
  (no `"modifications"` wrapper), it's still accepted as a 1-item list rather than
  raising a validation error.

**Proof:** `src/tests/test_tweak_extractor.py::test_four_part_compound_review_all_four_captured`
reproduces the exact review text from the sample data and asserts all 4 tweaks are
captured with the correct types, in order.

### 2. `featured_tweaks` (the actual "Featured Tweaks") was scraped but never used (HIGH)

**Found:** The scraper already outputs a `featured_tweaks` array per recipe — this
is AllRecipes' own highest-voted, community-tested tweaks section, i.e. exactly
what the assignment brief describes as the product's core input. The pipeline
never read this field. Instead, `extract_single_modification()` picked **one
random review** from the full, unfiltered `reviews` list (including reviews with
no modification at all), directly contradicting "applying the highest voted
community-tested modifications."

**Root cause:** the junior engineer's implementation never consumed the
`featured_tweaks` key from the scraped JSON.

**Fix:** `pipeline.py` gained `parse_featured_tweaks()` and
`select_source_reviews()`: prefer `featured_tweaks`; fall back to
`has_modification` reviews only when a recipe has none scraped. **All** selected
reviews are now processed (not one random pick), each potentially yielding
multiple modifications per finding #1.

**Proof:** `src/tests/test_pipeline_sourcing.py::test_select_source_reviews_prefers_featured_tweaks`
and `..._falls_back_when_no_featured_tweaks`.

### 3. Recipes with no tweaks silently vanished from output (MEDIUM — the scale bug)

**Found:** 2 of the 5 sample recipes (spiced purple plum jam, mango teriyaki
marinade) have **zero** reviews and zero `featured_tweaks`. `process_single_recipe`
returned `None` for these with only a log warning. `data/enhanced/` only ever
contained 2/5 recipes — i.e. the pipeline "scaled" to 40% of even the tiny sample
set, before considering any real-world variety.

**Root cause:** the empty-tweaks case was treated as a pipeline error rather than
a valid product state.

**Fix:** recipes with no available tweaks now still produce an `EnhancedRecipe`
with `modifications_applied = []`, `total_changes = 0`, and an explicit
`expected_impact` message ("No community-tested modifications were available for
this recipe.") instead of `None`. This lets a UI/consumer distinguish "no
community tweaks yet" (valid, common) from "the pipeline crashed" (a bug) — and
means all 5 sample recipes now produce output, not 2.

**Proof:** `src/tests/test_pipeline_sourcing.py::test_process_single_recipe_with_no_tweaks_returns_enhanced_recipe_not_none`.

### 4. Fuzzy-matched replace could silently no-op while reporting success (HIGH)

**Found:** `RecipeModifier.apply_edit`'s `"replace"` branch fuzzy-matches
`edit.find` against recipe lines using `SequenceMatcher` (not exact match), then
does a **literal substring replace**: `original_text.replace(edit.find, ...)`.
When the LLM's `find` text paraphrases the real ingredient line (e.g. LLM says
`"1 cup sugar"`, actual line is `"1 cup white sugar"`), the fuzzy match correctly
locates the right line — but the literal substring replace is a no-op. The code
still logged `"Replaced ... (similarity: 0.79)"` and appended a `ChangeRecord`
with `from_text == to_text`. **This is a false-positive diff**: exactly the kind
of bug that would make the product's headline feature (line-level diffs
explaining what changed and why) show a change that never happened.

**Root cause:** conflating "found the right line via fuzzy match" with "the exact
`find` substring exists in that line" — only the former is guaranteed.

**Fix:** if `edit.find` isn't an exact substring of the matched line, fall back to
replacing the **whole line** with `edit.replace` (justified — fuzzy match already
gave high confidence it's the right line). If the resulting text equals the
original (a true no-op), skip recording a `ChangeRecord` instead of reporting a
change that didn't happen.

**Proof:** `src/tests/test_recipe_modifier.py::test_replace_falls_back_to_whole_line_when_find_not_exact_substring`
and `test_replace_that_would_produce_no_change_is_not_recorded`.

### 5. `build_simple_prompt` never received the multi-modification fix (HIGH — caught before shipping)

**Found:** `TweakExtractor` actually calls `build_simple_prompt()`, which had its
own **duplicated copy** of the old single-object JSON schema — never updated when
`EXTRACTION_PROMPT`/`SYSTEM_PROMPT` were fixed for fix #1. Unit tests still passed
because they mock the LLM response directly and never inspect the outgoing prompt
text, so this would have silently shipped the *old* single-tweak-per-review
behavior to the real API despite the parsing/schema side being correct.

**Fix:** `build_simple_prompt` now delegates to `EXTRACTION_PROMPT.format(...)`
instead of duplicating the schema text, so there's exactly one definition.

### 6. Cost optimization: batch all of a recipe's reviews into one LLM call (MEDIUM)

**Found:** fixing #2 (process *all* `featured_tweaks` instead of one random
review) turned 1 LLM call/recipe into up to N calls/recipe (N = featured tweak
count, up to 5 in the sample data) — each call re-sending the full recipe
title/ingredients/instructions context. Correctness and cost were in tension.

**Fix:** added `extract_modifications_batch()` — sends **all** of a recipe's
reviews in a single LLM call, with each returned modification tagged
`review_index` to preserve attribution back to its source review
(`BatchModificationObject` / `BatchModificationExtractionResult` in `models.py`,
`build_batch_prompt` in `prompts.py`). This is now the primary path; the original
one-call-per-review loop is kept only as a fallback if the batch call fails
outright (e.g. truncated/malformed JSON on a very long batch), trading cost for
resilience only when actually needed. `max_tokens` scales with review count
(`min(4000, 800 + 400 * len(reviews))`) so batching doesn't truncate output.

Net effect: recipe with 5 featured tweaks goes from 5 LLM calls back down to 1 in
the common case, while still capturing every discrete modification in every
review (unlike the original single-random-review behavior).

**Proof:** `src/tests/test_tweak_extractor.py::test_extract_modifications_from_reviews_uses_one_batched_call`
asserts exactly 1 `chat.completions.create` call for 2 reviews yielding 4
modifications; `..._falls_back_per_review_on_batch_failure` proves the resilience
fallback still works when batching fails.

### 7. `output_dir` silently mismatched the README's own instructions (MEDIUM)

**Found:** during the live 6-recipe verification run (below), following the
README's documented steps exactly (`cd src && python test_pipeline.py all`)
produced enhanced output in `src/data/enhanced/` — not the repo-root
`data/enhanced/` that the README's "Enhanced recipes are saved in..." section,
and the originally-committed sample outputs, both assume.

**Root cause:** `test_pipeline.py` reads recipes from an explicit `"../data"`
path (correctly anchored relative to `src/`), but never passed a matching
`output_dir` to `LLMAnalysisPipeline()`. That left the library default,
`"data/enhanced"`, in effect — which resolves relative to the *current working
directory*, not the repo root. Two relative paths in the same script,
inconsistently anchored.

**Fix:** pass `output_dir="../data/enhanced"` explicitly in both
`test_single_recipe()` and `test_all_recipes()`, matching the existing
`../data` input path, so output always lands in one place regardless of
where the script happens to be invoked from. Consolidated the two
already-split output locations back into `data/enhanced/` and removed the
stray `src/data/` directory.

**Proof:** re-ran `python test_pipeline.py all` from `src/` after the fix;
output landed directly in the repo-root `data/enhanced/` as expected.

## Live Verification

The mocked tests prove the extraction logic is structurally correct, but the
real question is whether the actual OpenAI model, given the real prompt,
follows the new schema. Once a working API key was available (from a network
not blocking `api.openai.com`), the fixed pipeline was run for real against
`data/recipe_10813_best-chocolate-chip-cookies.json`.

Two of the three source reviews used were compound (the exact failure mode
called out in the assignment brief):

- *"I used an ice cream scoop, that made 16 big cookies. I did add an
  additional egg yolk to help keep the cookie chewy."* → correctly split into
  **2** modifications (`technique_change`: ice cream scoop; `addition`: egg
  yolk), instead of collapsing into one.
- *"...used a whole cup of white sugar and 1/2 c of brown... and 1/2 c less
  flour... added a tiny dash of cinnamon..."* → correctly split into **3**
  modifications (two `quantity_adjustment`s and one `addition`).

Result: **7 modifications extracted from 3 reviews, 10 line-level changes
applied**, vs. the pre-fix ceiling of exactly 1 modification per run. The
regenerated output is committed at
`data/enhanced/enhanced_10813_best-chocolate-chip-cookies.json`.

This run also surfaced a real infrastructure constraint worth documenting:
the primary working environment used for this assignment blocks outbound
calls to `api.openai.com` at the network/proxy level (confirmed via a direct
`PermissionDeniedError` with a corporate content-filter response body, not an
auth or quota error).

### Full 6-recipe run (Groq free tier)

To validate against all 6 scraped recipes without needing a paid OpenAI key,
free-tier provider support was added to `TweakExtractor` (Groq and Gemini,
both OpenAI-API-compatible, auto-detected via `GROQ_API_KEY`/`GEMINI_API_KEY`
env vars). A full run (`openai/gpt-oss-20b` via Groq) produced:

| Recipe | Modifications | Changes |
|---|---|---|
| Best Chocolate Chip Cookies | 5 | 5 |
| Creamy Sweet Potato With Ginger Soup | 10 | 6 |
| Spicy Apple Cake | 2 | 1 |
| Nikujaga (Japanese-Style Meat and Potatoes) | 1 | 1 |
| Spiced Purple Plum Jam | 0 | 0 (no source reviews available) |
| Mango Teriyaki Marinade | 0 | 0 (no source reviews available) |

The two 0-modification recipes are the correct, honest result of Fix #3
(graceful empty state) — they have no `featured_tweaks` or
`has_modification`-flagged reviews in the scraped data, not a pipeline
failure.

Running this exactly as the README instructed (`cd src && python
test_pipeline.py all`) surfaced one more bug: `test_pipeline.py` reads
recipes from an explicit `../data` path but never passed a matching
`output_dir` to `LLMAnalysisPipeline()`, so it silently used the library's
`"data/enhanced"` default — which resolves relative to the *current* working
directory, not the repo root. Every run following the README's own
instructions was therefore writing output to `src/data/enhanced/` instead of
the repo-root `data/enhanced/` that the rest of the README and the original
sample files assume. Fixed by passing `output_dir="../data/enhanced"`
explicitly, matching the existing `../data` input path, and consolidated the
two split output locations back into one.

## Technical Decisions & Rationale

- **List-of-modifications over a single merged object**: keeps `ModificationObject`
  itself simple (one type, one reasoning, one set of edits) and pushes the "one
  review can contain many tweaks" concern to a thin wrapper
  (`ModificationExtractionResult`) and the extractor's return type. This keeps
  `RecipeModifier.apply_modifications_batch` (already list-based) unchanged.
- **Featured tweaks preferred, reviews as fallback, not "either/or"**: keeps the
  pipeline functional for recipes the scraper didn't tag with `featured_tweaks`
  (schema drift/future scrapes), rather than hard-requiring the field.
- **Graceful empty-state over exception/None**: a recipe with no community tweaks
  is a normal, expected outcome for a long-tail catalog — not an error. Modeling
  it explicitly in `EnhancementSummary.expected_impact` is a product-thinking
  choice: users should see *why* a recipe wasn't enhanced, not just miss it.
- **Whole-line fallback over hard-failing the edit**: chosen over simply refusing
  the edit, because refusing would just reintroduce the "3 of 4 tweaks silently
  dropped" problem via a different code path. Whole-line replace is safe here
  specifically because `find_best_match` already enforces a similarity threshold
  before this branch is reached.
- **Mocked tests as the primary regression suite, live run as spot-check**:
  mocked tests stay fast, free, and runnable in CI/offline; a live API run was
  used once to spot-check that the real model actually follows the new schema
  (see "Live Verification" above), rather than relying on mocks alone or
  re-running the live API on every change.

## Implementation Details & Challenges

- The existing `data/enhanced/enhanced_10813...json` sample already didn't match
  what the pre-fix code could even produce (it had 2 `modifications_applied`
  entries; the pre-fix pipeline could only ever emit 1 per run) — a useful signal
  that the schema had already regressed at some point before this review.
- Pydantic's strict `Literal` typing on `modification_type` made the "compound
  review, one type" bug easy to prove structurally (a single object literally
  cannot represent two types) rather than just anecdotally.
- Added `pytest` as a dev dependency (`[dependency-groups].dev` in
  `pyproject.toml`) since no test runner previously existed — `test_pipeline.py`
  is a manual harness, not an automated suite.

## Future Improvements (explicitly out of scope for this pass)

- Regenerate `data/enhanced/*.json` for all 5 recipes against the real OpenAI API
  once a key is available, to validate prompt quality (not just schema
  correctness) on live output.
- `RecipeModifier`'s fuzzy matching is still line-level and single-target; a
  review that needs to touch two separate ingredient lines with very similar text
  could still mis-target. Not observed in the 5 samples, but plausible at scale.
- No dedup/conflict resolution across multiple applied modifications (e.g. two
  different featured tweaks both trying to change the same ingredient
  quantity) — currently applied sequentially in review order, last-write-wins.
- No confidence scoring or user-facing ranking of which featured tweaks were
  actually easy/safe to apply (`validate_modification_safety` exists but isn't
  wired into the pipeline output yet).
- Further cost optimization not yet done: no response caching (rerunning the
  pipeline on an unchanged recipe re-calls the LLM every time — cheap to add a
  content-hash cache keyed on recipe+review text), no skip-if-already-enhanced
  check in `process_recipe_directory` for repeated dev runs, and no evaluation of
  whether `gpt-3.5-turbo` could be swapped for an even cheaper/faster model
  (e.g. `gpt-4o-mini`) without losing extraction quality — worth an offline
  accuracy-vs-cost comparison before switching.
