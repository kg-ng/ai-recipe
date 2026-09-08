# Pipeline Lessons Learned

Persistent memory for agents working on `src/llm_pipeline/`. Before starting any
review or implementation task on this pipeline, read this file. After a review or
debate round surfaces a genuine gap, append a new entry at the bottom (never edit
or delete prior entries — this is a append-only log).

This is the raw, append-only agent memory. `docs/pipeline-fixes.md` is the
polished, human-facing writeup (assumptions, rationale, proof, future work) derived
from these entries — keep both in sync when a HIGH priority entry is added here.

Format per entry:
```
## <YYYY-MM-DD> — <short title>
Discovered:      <what was found>
Root cause:      <why it happened>
Fix applied:     <what changed, or "not fixed — deferred, see reason">
Target file(s):  <files touched>
Priority:        HIGH | MEDIUM | LOW
```

---

## 2026-09-08 — Compound reviews were silently truncated to one modification type
Discovered:      `ModificationObject` only allowed a single `modification_type` per
                 extraction. Real reviews routinely describe multiple independent
                 changes in one sentence (e.g. "added an egg and halved the sugar",
                 or the cookie recipe's 4-part review: sugar ratio + omit water +
                 add cream of tartar + refrigerate batter). Only the first/dominant
                 change was ever captured; the rest were dropped with no warning.
Root cause:      Schema and prompt were designed around "one review = one tweak",
                 and the few-shot examples themselves modeled two different
                 modification types crammed under one label (e.g. "addition" label
                 covering both an addition AND a removal).
Fix applied:     Added `ModificationExtractionResult` (a `modifications: List[...]`
                 wrapper). Prompt and few-shot examples rewritten to require one
                 entry per discrete, independently-describable change.
Target file(s):  src/llm_pipeline/models.py, src/llm_pipeline/prompts.py,
                 src/llm_pipeline/tweak_extractor.py
Priority:        HIGH

## 2026-09-08 — `featured_tweaks` field scraped but never consumed
Discovered:      Scraper output already includes a `featured_tweaks` array
                 (`is_featured: true`) — the actual highest-voted community tweaks
                 AllRecipes surfaces. The pipeline ignored it and instead picked
                 ONE random review from the generic `reviews` list via
                 `extract_single_modification`, contradicting the product's core
                 premise ("applying the highest voted community-tested
                 modifications").
Root cause:      Junior engineer's implementation never read the `featured_tweaks`
                 key from the scraped JSON.
Fix applied:     Pipeline now sources modifications from `featured_tweaks` (falling
                 back to `has_modification` reviews when absent), and processes ALL
                 of them per recipe instead of one random pick.
Target file(s):  src/llm_pipeline/pipeline.py
Priority:        HIGH

## 2026-09-08 — Recipes with no tweaks silently failed instead of degrading gracefully
Discovered:      2 of the 5 sample recipes (plum jam, mango teriyaki marinade) have
                 zero reviews and zero featured_tweaks. `process_single_recipe`
                 returned `None` for these with only a warning log — `data/enhanced/`
                 only ever contained 2/5 recipes, silently failing to "scale."
Root cause:      No explicit handling for the empty-tweaks case; treated as a
                 pipeline error rather than a valid product state.
Fix applied:     Recipes with no available tweaks now still produce an
                 `EnhancedRecipe` with zero modifications applied and an explicit
                 `expected_impact` message, so all 5 recipes produce output and the
                 UI/consumer can distinguish "no community tweaks yet" from "the
                 pipeline crashed."
Target file(s):  src/llm_pipeline/pipeline.py
Priority:        MEDIUM

## 2026-09-08 — Fuzzy-matched replace silently no-op'd while reporting success
Discovered:      `RecipeModifier.apply_edit`'s "replace" branch fuzzy-matches
                 `edit.find` against recipe lines (SequenceMatcher, not exact
                 match), then did a literal `original_text.replace(edit.find, ...)`.
                 When the LLM's `find` text paraphrased the real ingredient line
                 (e.g. "1 cup sugar" vs. actual "1 cup white sugar"), the fuzzy
                 match correctly located the line, but the literal substring
                 replace was a no-op — yet the code still logged "Replaced ...
                 (similarity: 0.79)" and appended a ChangeRecord with
                 from_text == to_text. This is a false-positive diff: the UI would
                 show "we changed X" when nothing changed.
Root cause:      Conflating "found the right line via fuzzy match" with "the
                 exact `find` substring exists in that line" — literal
                 `str.replace` assumes the latter but only the former is
                 guaranteed.
Fix applied:     If `edit.find` is not an exact substring of the matched line,
                 fall back to replacing the whole line with `edit.replace`
                 (we already have high fuzzy-match confidence it's the right
                 line). If the resulting text equals the original (truly no
                 change), skip recording a ChangeRecord instead of reporting a
                 false positive.
Target file(s):  src/llm_pipeline/recipe_modifier.py, src/tests/test_recipe_modifier.py
Priority:        HIGH

## 2026-09-08 — Prompt sync bug: `build_simple_prompt` never got the multi-modification fix
Discovered:      While adding cost-optimized batching, found that
                 `TweakExtractor` actually calls `build_simple_prompt()`, not
                 `EXTRACTION_PROMPT` directly. `build_simple_prompt` had its own
                 duplicated copy of the OLD single-object JSON schema that was
                 never updated when `EXTRACTION_PROMPT`/`SYSTEM_PROMPT` were fixed
                 for multi-modification extraction. Unit tests still passed
                 because they mock the LLM response directly and never inspect
                 the outgoing prompt text - so this would have silently shipped
                 the old single-tweak-per-review behavior to the real API despite
                 the schema/parsing fix being correct.
Root cause:      Prompt text was duplicated in two places (`EXTRACTION_PROMPT`
                 and `build_simple_prompt`) instead of one function reusing the
                 other; the first fix pass only updated one of the two.
Fix applied:     `build_simple_prompt` now delegates to
                 `EXTRACTION_PROMPT.format(...)` instead of duplicating the
                 schema text, so there is exactly one place defining it.
Target file(s):  src/llm_pipeline/prompts.py
Priority:        HIGH

## 2026-09-08 — Cost optimization: batch all reviews for a recipe into 1 LLM call
Discovered:      The featured_tweaks fix (processing ALL of a recipe's featured
                 tweaks instead of one random review) turned 1 LLM call/recipe
                 into N calls/recipe - each call re-sending the full recipe
                 title/ingredients/instructions context. For recipes with several
                 featured tweaks (up to 5 in the sample data) this is a ~5x cost
                 increase with heavy duplicated context tokens.
Root cause:      Correctness fix (process all featured tweaks) and cost
                 (minimize LLM calls) were in tension; the first pass optimized
                 only for correctness.
Fix applied:     Added `extract_modifications_batch()` - sends ALL of a recipe's
                 reviews in ONE LLM call, tagging each returned modification with
                 a `review_index` back to its source review
                 (`BatchModificationObject`/`BatchModificationExtractionResult` in
                 models.py, `build_batch_prompt` in prompts.py). This is now the
                 primary path in `extract_modifications_from_reviews`; the
                 original one-call-per-review loop is kept as a fallback used
                 only if the batch call fails outright (e.g. truncated/malformed
                 response), trading cost for resilience only when needed.
Target file(s):  src/llm_pipeline/models.py, src/llm_pipeline/prompts.py,
                 src/llm_pipeline/tweak_extractor.py, src/tests/test_tweak_extractor.py
Priority:        MEDIUM
