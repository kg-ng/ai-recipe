# Agentic System

This directory defines the agent/skill setup Copilot CLI uses when working in this
repository. Adapted from a personal, generic agent/skill library (not tied to any
employer's proprietary systems) and customized for this repo's Python recipe-tweak
pipeline (`src/llm_pipeline/`).

## Agents (`.github/agents/`)

| Agent | Purpose |
|---|---|
| `pipeline-planner` | Entry point. Understands intent, breaks down work, delegates to the right agent/skill. |
| `pipeline-qa-reviewer` | Read-only. Verifies the pipeline runs end-to-end, captures ALL discrete tweaks per review (not just the first clause), and doesn't overfit to the 5 sample recipes. |
| `pipeline-commit` | Stages and commits approved changes using Conventional Commits. Never pushes. |
| `pipeline-pr-preparer` | Runs pre-PR checks (pipeline run, lint, scale/correctness spot-checks) and drafts a PR description. |
| `rubber-duck` | Generic logic reviewer — correctness, edge cases, flawed assumptions. |

## Memory (`.github/agents/pipeline-lessons.md`)

Append-only log of gaps discovered during review/implementation (what was found,
root cause, fix applied, priority). `pipeline-planner` reads it before planning;
`pipeline-qa-reviewer` reads it before reviewing and appends new findings after.
This prevents re-discovering (or silently regressing) the same issues across
sessions — e.g. the multi-tweak extraction bug and the unused `featured_tweaks`
field are already logged there.

## Skills (`.github/skills/`)

Generic engineering-practice skills (planning, TDD, code review, git workflow,
debugging, docs/ADRs, security, incremental implementation, doubt-driven
development, shipping checklists). Command examples were adapted from
npm/Next.js originals to this repo's `uv`/Python tooling.
