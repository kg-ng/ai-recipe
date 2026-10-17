# Recipe Enhancement Platform

LLM pipeline that reads community review tweaks for a recipe, extracts each one as structured edits, and applies
them to the recipe with citations. See `README.md` for usage and results.

## Layout
```
src/llm_pipeline/        pipeline.py (orchestration), tweak_extractor.py (LLM step), recipe_modifier.py
                         (deterministic edit application), models.py, prompts.py, enhanced_recipe_generator.py
src/evals/               golden sets, metrics, runner, keyword baseline (see README "Evaluation")
src/tests/, src/test_pipeline.py   pytest suite
src/scraper_v2.py        optional scraper; data is already provided in data/
data/                    scraped recipes (coursework data, not licensed for reuse) and enhanced output
docs/                    pipeline-fixes.md (write-up), pipeline-lessons.md (append-only agent memory)
```

## Commands
```bash
cd src && python -m pytest                       # or: uv run pytest. Live-LLM tests are skipped without a key
cd src && RUN_LIVE_LLM_TESTS=1 python -m pytest test_pipeline.py   # needs OPENAI_API_KEY, GROQ_API_KEY or GEMINI_API_KEY
cd src && python -m evals.run_eval               # offline evals: baseline, review-selection ceiling, modifier
cd src && python -m evals.run_eval --predictor llm-pipeline   # real model; needs a key
```

## Team (`.claude/agents/`)
| Agent | Use it to |
|---|---|
| `pipeline-planner` | Start here. Understands intent, plans, delegates. Reads `docs/pipeline-lessons.md` first. |
| `pipeline-qa-reviewer` | Read-only review: does extraction capture every discrete tweak in a review, does the pipeline run end to end, does it overfit the sample recipes. |
| `pipeline-commit` | Stage and commit approved changes (Conventional Commits). Never pushes. |
| `pipeline-pr-preparer` | Run the pre-PR gates and draft the PR description. |
| `rubber-duck` | Generic logic review: correctness, edge cases, flawed assumptions. |

Skills in `.claude/skills/` are generic engineering practices (planning, TDD, review, git workflow, debugging, ADRs,
security, doubt-driven development, shipping). They are copies of the `agentic-system` skills.

## Rules for working here
- **Measure before and after.** A change to extraction, selection or the modifier should be checked with
  `python -m evals.run_eval`; add a golden-set case for any new failure you find.
- `RecipeModifier` refuses ambiguous matches on purpose. Do not loosen it to make an edit apply; fix the `find` text.
- The review-selection gate currently loses some real tweaks (the README reports the measured ceiling). Widening it
  sends more reviews to the LLM, which is a cost decision: measure it with a real run first.
- Append to `docs/pipeline-lessons.md` when a review surfaces a genuine gap; never edit earlier entries.
- Do not republish `data/`. It is third-party content kept for reproducibility.
