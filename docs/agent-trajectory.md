# Agent Trajectory

A chronological record of the coding-agent session used to diagnose and fix
the recipe-tweak enhancement pipeline, and to stand up a supporting agentic
workflow for this repo. Reconstructed from the session history as a
structured summary (not a raw log export).

---

## 1. Stand up an agentic workflow for this repo

**Ask:** Build/customize an agentic system to support ongoing work on this
pipeline — agents and skills, callable from the Copilot CLI.

**What was built (`.github/`):**

- **Agents**
  - `pipeline-planner` — entry point; clarifies intent, maps the request onto
    pipeline stages (`scraper_v2.py` → `tweak_extractor.py` →
    `recipe_modifier.py` → `enhanced_recipe_generator.py`/`pipeline.py`),
    and delegates.
  - `pipeline-qa-reviewer` — reviews changes before they're considered done;
    reads/writes a persistent lessons log.
  - `pipeline-commit` — handles staging/committing work in logical groups.
  - `pipeline-pr-preparer` — prepares PR descriptions when needed.
  - `rubber-duck` — general reasoning/sounding-board agent.
- **Skills** — a library of reusable playbooks invoked by the agents above:
  test-driven development, doubt-driven development, debugging and error
  recovery, planning and task breakdown, incremental implementation, code
  review and quality, documentation and ADRs, git workflow and versioning,
  security and hardening, shipping and launch, and a couple of
  communication-style skills. All commands/examples inside were adapted to
  this repo's actual tooling (`uv`, `pytest`, Python) rather than left
  generic.
- **Memory** — `.github/agents/pipeline-lessons.md`, an append-only log the
  planner reads before planning and the QA reviewer updates after each
  finding, so bugs and root causes accumulate across sessions instead of
  being rediscovered.
- **Index** — `.github/AGENTS_README.md` documenting how the pieces fit
  together.

**Outcome:** confirmed working and ready to use for the actual pipeline
investigation below.

---

## 2. Diagnose the pipeline problem

**Ask:** Per the assignment brief — figure out whether the pipeline "works
beyond a couple of superficial examples," using the two hints given (missed
compound modifications, hard-coded assumptions that don't scale past the 5
sample recipes).

**Investigation, in order:**

1. Read `src/llm_pipeline/pipeline.py`, `tweak_extractor.py`, `models.py`,
   `prompts.py`, `recipe_modifier.py`, `enhanced_recipe_generator.py`.
2. Checked `data/enhanced/*.json` against `data/recipe_*.json` — found only
   2 of 5 sample recipes had ever produced enhanced output.
3. Noticed the raw scraped recipe data has a `featured_tweaks` field
   (reviews flagged `is_featured: true`) — this is literally the "Featured
   Tweaks" the assignment describes — but the pipeline never read it, only
   a generic `reviews` list.
4. Traced the extraction prompt and parsing logic and confirmed it was
   built to return exactly one modification object, discarding any
   additional modifications described in the same review sentence.
5. No `OPENAI_API_KEY` was available in this environment, so validation was
   done with a mocked OpenAI client rather than live API calls (explicitly
   agreed with the user rather than skipped silently).

**Bugs found and fixed:**

1. **Compound modifications dropped.** A review like "I added an egg and
   halved the sugar" only ever yielded one modification. Rewrote the
   extraction prompt/schema to return a list of modifications per review.
2. **`featured_tweaks` never sourced.** Added logic to prefer
   `featured_tweaks` over generic reviews, with a documented fallback for
   recipes that don't have any.
3. **Silent drops on empty input.** Recipes with zero eligible reviews
   returned `None` and were skipped entirely instead of producing an honest
   "no community modifications found" result.
4. **False-positive diffs.** The replace step in `recipe_modifier.py` could
   fuzzy-match a line, fail to find the exact substring inside it, and
   still record a "successful" change with no actual text difference. Fixed
   to fall back to a whole-line replace or skip recording the change.
5. **Stale duplicated prompt.** The function actually used at call time
   (`build_simple_prompt`) had its own old copy of the single-modification
   schema that was never updated when the main prompt was fixed — meaning
   a real API call would still have received broken instructions. Fixed by
   having it delegate to the single source of truth.
6. **Cost blowup from the correctness fix.** Processing every review
   individually (needed for fix #2) turned one LLM call per recipe into up
   to N calls per recipe. Added a single batched extraction call per
   recipe (reviews tagged by index), falling back to per-review calls only
   if the batch call fails.

**Verification:** wrote 16 unit tests (mocked OpenAI, no API key required)
covering compound-sentence splitting, `featured_tweaks` sourcing and
fallback, empty-recipe handling, batch vs. per-review fallback behavior,
and the no-op-safe replace path. All 16 passed. Findings and rationale were
written up in `docs/pipeline-fixes.md` and logged in the lessons file.

---

## 3. Documentation pass

**Ask:** Update the README with what changed and why.

- Updated `README.md` — "How It Works" section now reflects the real
  sourcing/batching/error-handling behavior; added an "Agentic System"
  section describing the workflow from step 1.
- Authored `docs/pipeline-fixes.md` as the comprehensive write-up:
  Assumptions, Problem Analysis (per-bug root cause + proof), Technical
  Decisions and Rationale, Implementation Details and Challenges, Future
  Improvements.

---

## 4. Deliverables gap-check and repo setup

**Ask:** Confirm whether all assignment deliverables were satisfied.

Walked through the checklist and found gaps:
- The working directory's `origin` still pointed at the original assignment
  repository rather than a private clone.
- Nothing had been committed yet — all pipeline/doc/agent-system changes
  were still staged or untracked.
- No trajectory file existed (this document).
- Video presentation still outstanding (requires the human to record).

**Actions taken:**
1. Created a new private GitHub repository under the user's own account and
   re-pointed `origin` to it, keeping the original repository as `upstream`
   for reference only.
2. Pushed `main`.
3. Committed the work in two logical groups: the agentic system, then the
   pipeline fixes/tests/docs together.
4. Pushed the feature branch, merged it into `main` directly (no PR needed
   since this is a private, single-owner repo), and pushed `main`.

**Outstanding after this session:** invite the Casper team as collaborators
on the private repo, record the video presentation, and (optionally) run a
live end-to-end pass once an OpenAI API key is available to regenerate
`data/enhanced/*.json` for all 5 sample recipes.
