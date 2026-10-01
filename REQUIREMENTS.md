# Requirements — decision models on multi-step browser tasks

## Question

How well do System One models (typed, calibrated decision models such as Jev, decider-4b, jevk5) control multi-step browser tasks — and when should an agent stop trusting them and escalate to an LLM? Benchmark name: S1Bench.

## Why this is new

- JevBench scores single decisions (ranking, calibration). Nothing public measures multi-step browser control, where one wrong step derails the task.
- Evidence it matters: decider-4b ties Jev at Show HN ranking (AUC 0.694 vs 0.735) but failed Google Flights 0/2 at the airport dropdown (0.041 on the right option). Jev passed 2/2 (0.89). Notes: `open jev models test`.

## Ours vs reused

- **Reused, credited:** browser-use/jev-ultrafast agent loop (MIT). Upstream remote kept.
- **Ours:** the task pages, their variations and traps, per-step ground truth, scoring, the escalation analysis.
- Not building another browser agent — a dozen exist.

## Contenders

| Model | Where | Cost |
|---|---|---|
| Jev (`jev-latest`) | classifier.dev, Jev-compatible `/v1/systemone` | $5 signup credit |
| decider-4b v2 | local, MPS | free |
| jevk5 | local | free — confirm it installs and speaks the same API |

Any endpoint that speaks the System One API (`/v1/systemone`) plugs in via `TYPESAFE_BASE_URL` / `TYPESAFE_MODEL`. Others can add models with their own keys.

## Test design

Adaptation is the point, so pages change — but in a controlled way, so every model sees the same changes.

1. **Seeded local pages** (main set). Each task is one page generator; a seed picks layout, labels, element order, distractor count, dropdown delay. Same seed list for every model.
2. **Saved real pages.** HTML snapshots of real sites, served locally. Real-web mess, frozen.
3. **Live sites** (sanity check only, labelled not reproducible). The existing Google Flights runs count here.

### Candidate tasks (6–8)

- Airport autocomplete — type, then pick the right suggestion among lookalikes (the decider failure). **First.**
- Date picker — navigate months, pick one day
- Form with validation — fill, read the error, fix
- Search + filter a list, open one item
- Checkout — go up to payment, stop (must not click Pay)
- Settings — change one toggle next to a destructive one
- Interruptions — cookie banner or modal mid-task
- Pagination — find an item not on page 1

### Traps (applied across tasks by seed)

- **Position bias** — same page, elements shuffled. Lev reports ~13% of Jev choices flip.
- **Distractors** — tempting wrong option beside the right one.
- **Prompt injection** — page text telling the agent to abandon the goal.
- **Timing** — suggestions/results appear after a delay.

## Scoring

- **Step accuracy** — each step's chosen action vs the accepted set for that state.
- **Task success** — goal reached, verified from page state, not the model's DONE.
- **Position-bias flip rate** — choice changes between original and shuffled page.
- **Injection resistance** — share of injected pages where the model stays on goal.
- **Calibration** — does confidence predict a wrong step? AUC and Brier on step correctness.
- **Escalation curve** — per model: threshold → % of wrong steps caught vs % of steps escalated. The practical output.
- **Speed and cost** — median s/step, tokens per task.

## Harness requirements

- Pages served from localhost; no external network for the main set.
- Ground truth lives **outside the DOM** (JSON per task/state), never as page attributes — the model reads the page.
- Record every model exchange (request, choice, probabilities, latency) to JSONL; score from the log, not live.
- Every run is reproducible from (task, seed, model, harness commit).
- One command runs a model across the full seed set; one command scores all logs into a table.
- Chrome remote debugging on only during runs.

## Non-goals

- Games (chess, match-3, cards) — already covered elsewhere and they test search, not single decisions.
- A leaderboard or paid LLMs.
- Tuning prompts per model.

## Constraints

- $5 classifier.dev credit; ~45k input tokens per 10-step task, so ~1,000+ task runs in budget.
- classifier.dev refuses some networks it flags as proxies; if Jev requests are rejected, try another network.
- Local models on M4 Pro, 24 GB. decider-4b ~12 s/step on MPS.

## Deliverables

1. Public repo: pages, harness patch, logs, scoring script, README with reproduce steps.
2. Results table + escalation curves.
3. Write-up post.

## Open questions

- Does jevk5 install cleanly and accept the same request shape?
- Steps with more than one correct action — accepted set per state, or one canonical path?
- How many seeds per task for stable numbers — start with 10, check variance.

## First milestone

Airport autocomplete page with a seed, its ground truth JSON, one Jev run and one decider run scored step by step.
