# CLAUDE.md

Instructions for AI coding agents (Claude Code, Codex, etc.) working in this repo. `AGENTS.md` is a symlink to this file.

## Before planning or writing any code

1. If `internal/` exists at the repo root, read and follow `internal/README.md` first. It takes priority over this file. It's gitignored, so list it with `ls internal/`; search tools skip it.
2. Open [docs/INDEX.md](docs/INDEX.md) and load only the docs it routes your task to. Never read `docs/archive/` unless asked.

## Keep docs and responses short

Every doc, plan, comment and response is as short as it can be while complete. Bullets over prose. No preambles, no closing summaries, no restating what was just said.

## Workflow

For every non-trivial task:
1. Read the plan or spec for it (via the index).
2. Explore the affected code before proposing changes.
3. Write a plan: what changes, what doesn't, what could break, which tests cover it.
4. Wait for approval.
5. Execute against the plan. If reality forces a deviation, stop and report; don't improvise.
6. Run `make check` and `make test` before declaring done.
7. Summarize what changed and what the reviewer should look at.

Never commit or push unless asked.

## Benchmark rules

A benchmark is worth only as much as it reproduces. These rules beat convenience.

- **The harness is frozen.** `s1bench/harness/` is adapted from [browser-use/jev-ultrafast](https://github.com/browser-use/jev-ultrafast) at `1231850` (MIT), with a configurable endpoint and timeout and single-option target heads trimmed. Request bodies match the reference key for key, in the same key order. Any change there changes every recorded body hash, so it needs an ADR and a fresh collection.
- **The page is the world; the oracle holds the goal.** Answers (accepted airports, trip type) never enter a task page, its URL, title or accessible names. The oracle passes them in as arguments.
- **Page time moves only on WAIT.** No timers, `Date`, `Intl`, animations or transitions in task pages.
- **Determinism.** Seed randomness with strings (`random.Random(f"airport:{seed}")`), never `hash()`, which is randomised per process. Never sort keys in request JSON: key order is part of the model's input. The page server stays on `127.0.0.1:8777`, because the URL is inside every request.
- **Never touch a real browser.** Import `browser_harness` only through `s1bench` (its `__init__` forces `BU_NAME=s1bench`), drive only the bench's headless Chrome with a throwaway profile, and assert `HeadlessChrome` before acting.
- **Outcomes come from page state.** A model's DONE is not success.
- **Scores come from logs, not live runs.** Every number in a results table traces to a committed log.
- **Tests never call paid APIs or the network.**

## Code conventions

- Python 3.12, run through `uv`. Ruff is the source of truth for lint and format.
- Type every signature; `pyright` in standard mode must pass.
- Public modules, classes and functions get Google-style docstrings that state the contract for callers (ruff `D`; tests exempt). Comments explain *why* a line is written the way it is.
- Names describe intent. No dead code, no commented-out blocks, no TODO without an issue link.
- Small, pure functions where reasonable; browser, network and file effects at the edges.
- Match the existing approach. Don't add a second pattern for a problem the code already solves.

## Architectural philosophy

- **YAGNI.** No library, abstraction or pattern until the need is proven.
- **Boring technology.** Stdlib and proven tools over novel ones; justify anything trendy.
- **Simple over clever.** Would a stranger reading this in 6 months understand what's happening and why? If not, simplify.
- **Leave working code alone.** Don't refactor for taste.

## Testing

- Protect what the numbers depend on: request bodies (golden tests), labels (oracle and brute-force checks), scoring maths.
- Deterministic: no network, no real clocks without freezing them.
- Test names state the scenario and the expected outcome.
- When fixing a bug, first write the test that would have caught it.

## Dependencies and security

- Add dependencies only with `uv add`, never by hand-editing versions, after confirming the exact package name is real and maintained. Each one needs a reason.
- Secrets live in environment variables or the keychain; `.env` is ignored. If you see a secret in code, stop and flag it.

## Documentation

- **ADRs** for non-obvious decisions: `docs/adr/NNN-title.md` from `docs/adr/TEMPLATE.md`. Anything touching the harness, the request body or the scoring maths gets one.
- **Specs** for non-trivial features: `docs/specs/NNN-feature.md` from `docs/specs/TEMPLATE.md`.
- **Plans** live in `docs/plans/`. The chunk list is `docs/plans/003-build-order.md`; tick a chunk in the commit that finishes it.
- After adding or removing a doc, or finishing a chunk that changes how to run things, update `docs/INDEX.md` and the project context below.

## When stuck

1. Re-read the plan, this file and the relevant ADRs.
2. Read the code around the problem.
3. Check current library docs and source; don't trust memory.
4. Still unclear: stop and ask, with what you tried, what you found and the specific question.

Don't loop on cosmetic variations of the same fix, disable a failing test, swallow an exception, or mock in production code.

## Project context

- **Stack:** Python 3.12 with uv; browser-harness 0.1.13 (Chrome DevTools Protocol) and httpx; headless Chrome; Node 24 for task-page tests (`node --test`).
- **Layout:** `s1bench/` is the package. `s1bench/harness/` holds the adapted agent loop; task specs, pages, runner, replay and scoring sit beside it. Tests are in `tests/`.
- **Checks:** `uv sync`, then `make check` (ruff, format check, pyright) and `make test` (pytest). `make fix` applies what the tools can fix.
- **Benchmark commands:** none yet; they land chunk by chunk (`docs/plans/003-build-order.md`).
- **Don't touch:** `uv.lock` by hand; `datasets/` and `results/` except through the commands that write them.
