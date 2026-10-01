# Plan 003: Build order (M1)

**Status:** Approved
**Date:** 2026-10-01

Each chunk is one thing working end to end that you can run and see, sized for one session. Tick a chunk's box in the commit that finishes it. Chunks after the skeleton are rough and get re-cut when we reach them. The detail for each chunk is in [002](002-m1-implementation.md); its step numbers are in brackets.

## Why this order

- **Walking skeleton first.** By chunk 7, seed 0 runs page → headless Chrome → harness → agent loop → records → score table, with a scripted policy and no model. Every later chunk plugs into a path that already runs.
- **Ground truth before models.** Labels are what every model is scored against, and building them needs no paid API.
- **Parity after the loop runs,** so the golden request body comes from a real observation, not a hand-made fixture.
- **Variety, then the lexical gate, then paid runs.** If string matching solves the lookalikes, the spec gets fixed before any money is spent.

This replaces the 19-chunk order of 2026-09-29, which built one layer per chunk. Its chunk 2 (`validate_choice`, `action_space`) is now chunk 11.

## Ports

- Page server: `127.0.0.1:8777`. Fixed, because the URL is inside every request body.
- decider-4b: `127.0.0.1:8767`.
- Headless Chrome: `--remote-debugging-port=0` (random), only during runs.

## Chunks

**A. Walking skeleton (seed 0, no model)**
- [x] 1. Package skeleton: `s1bench/` forces `BU_NAME`, so the bench can't drive your real Chrome.
- [ ] 2a. Serve a seeded page: `spec(0)` with one city pair and fixed labels, `server.py`, the shell page and a static form. See: the form at the printed URL. [3, 5]
- [ ] 2b. Solve it by hand: `airport.mjs` as `step` + `view` + `mount` (instant suggestions, one-way, Search, results), with Node tests on `step`. See: you solve seed 0 in your browser and the results line names both airports. [4]
- [ ] 3. Headless Chrome the bench owns: `chrome.py` (throwaway profile, `DevToolsActivePort`, teardown in `finally`) and the harness `Browser` opening a tab. Adds Browser Use's MIT notice. See: `smoke` prints the page title and a `HeadlessChrome` user agent. [5]
- [ ] 4. See the page as a model does: port `snapshot.js` and `Browser.observe`. See: `smoke` prints the numbered action list for seed 0.
- [ ] 5. Act on it: port `Browser.act` and `fresh`, plus the page's `__bench.goal(accept)`. See: `smoke` plays a scripted path and prints "goal met".
- [ ] 6. The agent loop: port `Agent` with the `decide`, `write_text` and `after_action` hooks, a scripted policy and the oracle filler. See: `run collect --seeds 0` streams its steps, ends in `success` and writes one JSONL record per step. [2, 6]
- [ ] 7. Score it: `score.py` reads the records and prints a one-row table. See: `oracle | 1/1 success | N steps`. **Skeleton done.** [8]

**B. Ground truth**
- [ ] 8. Distances and labels: the lookup table, reverse BFS and `label()`, checked against brute-force BFS. See: `collect` prints every candidate's label at each step. [4]
- [ ] 9. Policies from labels: `oracle` and `epsilon` replace the script; outcome classes and the stale-retry canary. See: an epsilon run takes a wrong turn, recovers and succeeds. [6]
- [ ] 10. Time moves on WAIT: suggestion and result delays, loading lines, `tick()`. See: WAIT labelled progress while "Loading airports…" shows. [4]

**C. The request a model sees (parity with jev-ultrafast)**
- [ ] 11. `validate_choice` and `action_space`. See: the indexed elements a model gets for a real seed-0 observation. [1]
- [ ] 12. Questions and `build_request`, with a golden body test. See: the seed-0 request body, identical to upstream's for the same page. [1]
- [ ] 13. `parse_answers`, `post_json` and `choose`. See: a stub contender on localhost answers, and the run follows its choice. [1]
- [ ] 14. Records and dataset: `wire.py` with `body_sha256`, a deterministic `m1.jsonl.gz` and the manifest. See: two collections of seeds 0–4 compare byte-identical. [6]

**D. The full task**
- [ ] 15. Seeded variety: 14 city pairs, lookalikes in spread positions, 4 goal paraphrases and name forms; spec tests with a golden hash. See: seeds 0–4 look different in the browser. [3]
- [ ] 16. Free-text matching: "Portland" lists every lookalike, "Portland, Maine" only PWM. [4]
- [ ] 17. Distractors and Book: promo code, Swap, currency, trip as a select or radios, Book buttons (irreversible). [3, 4]
- [ ] 18. Full smoke: candidates equal the machine's actions, `elementFromPoint`, no answer leaks, worst-case height. See: `smoke --seeds 0-4` passes. [5]
- [ ] 19. Lexical gate: `random` and `lexical` policies; lexical option-only accuracy must be ≤ 0.6 over seeds 0–49. [6; change 15]

**E. Models**
- [ ] 20. Offline replay: `replay --contender random|lexical`, resumable, with row statuses. See: random scores about chance. [7]
- [ ] 21. HTTP contenders: `jev-classifier`, `decider-4b` and `custom`, plus `--dry-run`. See: the dry run's request count and token estimate. [7]
- [ ] 22. Step accuracy: per phase, the error mix, a bootstrap CI over seeds. [8]
- [ ] 23. Confidence signals: AUROC, AURC, coverage at risk, Brier, risk–coverage CSVs. [8]
- [ ] 24. Closed loop: `run closed --contender lexical --seeds 0-4`, with a paired 2×2 per seed. [9]
- [ ] 25. Mercury text: `field_context` and `field_text` for `--text mercury`. [9]

**F. Ship M1**
- [ ] 26. Reproduce steps in the README, `results/bench/m1/`, the REQUIREMENTS.md updates, and a pre-push review: MIT notice present, no personal notes in tracked docs. [10]

Then the live runs in 002's Verification section: Jev replay, decider replay, closed loop, `score --out results/bench/m1`.

## After M1

As in 002's "After M1": shuffle, relabel and injection variants, LLM escalation, more tasks. Planned once the M1 numbers are in.
