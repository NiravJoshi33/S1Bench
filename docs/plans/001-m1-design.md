# Plan: S1Bench, a benchmark for System One models in multi-step control. Milestone 1 (airport autocomplete)

> Design of record. [002-m1-implementation.md](002-m1-implementation.md) corrects 16 points; where they disagree, 002 wins. `bench/` is now `s1bench/` and `jev_ultrafast/` is now `s1bench/harness/`.

S1Bench scores any model that speaks the System One API (`/v1/systemone`: typed questions in, probabilities and confidence out). Jev is one contender, not the subject.

## Context

JevBench scores single decisions. Nothing public measures whether a System One model's confidence flags the steps it gets wrong in a multi-step task. That property decides whether such a model can run a loop and hand off to an LLM only when unsure.

Our own evidence:
- decider-4b ties Jev at single-decision ranking but failed Google Flights 0/2 at the airport dropdown.
- Our two classifier.dev Jev runs show both valid-path ambiguity (step 0 split ~50/50) and a hidden near miss (BLOCKED at 0.23 confidence, saved only because the page was stale).

Milestone 1 (M1) proves the whole pipeline on one task before scaling to 6–8 tasks:

    seeded local page → oracle labels every candidate → replay dataset → model runs → scored table

Decided with you:
- Closed-loop runs type text with an **oracle filler**, plus a few **Mercury** runs for the full-system number. This is a bench-only exception to AGENTS.md's "TYPE_TEXT invokes the text LLM"; the agent's default is unchanged.
- Build **M1 end-to-end**, look at the numbers, then plan M2.

Outcome, as four commands:
- `bench.run collect` builds the dataset with no model calls.
- `bench.replay` sends every recorded request to one model, with no browser.
- `bench.run closed` lets a model drive the page.
- `bench.score` writes the table and risk–coverage curves.

No commits unless you ask.

## Design rules (everything below follows from these)

1. **The page is the world; the oracle holds the goal.**
   - Python generates the task spec from the seed. The page receives only what a real site would show.
   - The answer set (accepted airports, trip type) never enters the page. The oracle passes it as an argument when it calls into the page.
   - Why: the snapshot sends the URL, title, visible text and accessible names to the model, so anything in the page can leak. REQUIREMENTS.md already demands ground truth outside the DOM.
2. **Page time moves only on WAIT.**
   - Suggestions and results appear after k WAITs, and a static "Loading…" line is shown until then.
   - Why: decider takes ~12 s per step. With real timers, slow models get free waits and the delay knob measures latency, not judgment.
   - Why WAIT and not every action: ticking on every action makes a 1-tick delay invisible, and it makes pointless clicks during loading count as progress.
3. **Ground truth is a function.**
   - Each task is a small state machine: `step(state, action) → state`.
   - BFS gives the number of actions left to the goal. Each candidate is labelled by whether taking it lowers that number.
   - Why: a JSON file per state only covers the states you listed, while closed-loop runs reach others. The page's UI is rendered from the same state machine, so labels can't drift from behaviour.
4. **Replay is the benchmark; closed loop checks it.**
   - Every model sees byte-identical requests.
   - Adding a model needs no Chrome.
5. **One runner for collection and closed loop.**
   - The existing `Agent` runs both. Collection just uses an oracle policy instead of a model.
   - Why: recorded requests are then exactly what the agent sends, with no second copy of the history or `page_changed` logic.
6. **A dedicated headless Chrome with a throwaway profile.**
   - It avoids the approval popup and your profile's state (the runs show INR prices and a pre-filled Ahmedabad).
   - Remote debugging is on only during runs.

## Steps (each testable on its own; steps 0–9 need no paid API)

### 0. Baseline
- Run `uv sync` and the checks.
- Expect exactly one failure: `tests/test_agent.py:96`. Commit 4f4ed0f added single-option trimming, so `type_text_target` is no longer posted.

### 1. Split the model call (`jev_ultrafast/model.py`)
- `build_request(page, goal, history, model=None) -> (body, meta)`: today's lines ~82–122 (action space, questions, single-head trimming).
- `parse_answers(result, meta)`: lines ~124–151 (synthesize single heads, validate, map to action ids).
- `choose()` composes build → `post_json` → parse, with the same return shape and timing.
- `post_json(url, key, body, timeout=httpx.USE_CLIENT_DEFAULT)`. Gotcha: `timeout=None` means *no timeout* in httpx.
- Tests:
  - fix line 96 to `{"operation", "click_target"}` and assert the synthesized `type_text_target` has p = 1.0;
  - a golden test that `build_request(page())` equals the body `choose()` posts;
  - timeout pass-through.

### 2. Agent hooks (`jev_ultrafast/agent.py`)
- Add class attributes `decide = write_text = after_action = None` plus keyword-only constructor arguments. Resolve them when called:
  - `(self.decide or choose)(…)` at L77
  - `(self.write_text or field_text)(context)` at L113
- Why not default parameters: defaults would freeze the functions and break the tests that monkeypatch `loop.field_text` (test_agent.py:191, 204). The `Agent.__new__` test fixture never runs `__init__`.
- Build the history entry (every decision and helper key) **before** `browser.act` (L117). After `act`, set `executed_ms`/`elapsed_ms`, append the entry, call `after_action(state)`, then observe (L142).
  - Why: today a missing key raises after the click was sent, so the action runs but is never logged.
- Tests:
  - call order is `act` → `after_action` (entry already in history) → `observe`;
  - a decision missing `usage` raises before `act`;
  - all existing tests pass unchanged.

### 3. Task spec in Python (`bench/__init__.py`, `bench/airport.py`)
- `bench/__init__.py` calls `os.environ.setdefault` for `BU_NAME="s1bench"` and `BH_TAB_MARKER="0"`.
  - Gotcha: browser_harness reads `BU_NAME` at import time. Importing `jev_ultrafast` first silently drives your real Chrome.
- `spec(seed)` returns `{goal, page, accept, values}`:
  - **`page`** (presentation only):
    - field-label wordings (e.g. "Where from?", "Origin"; unique, no `→`) and control order;
    - trip control: native radios or native select, usually defaulting to round trip;
    - 3–8 suggestions per city including real lookalikes, with the correct position spread across seeds;
    - neutral option values `o1…`;
    - delays of 0–2 WAITs for suggestions and for results;
    - 0–3 distractors (Promo code field, Swap button, currency select);
    - result rows, each with a Book button.
  - **`accept`**: the accepted airport codes and one-way.
    - Some seeds are city-level (London UK = LHR/LGW/STN/LTN/LCY/SEN/"All airports").
    - Some name a specific airport.
  - **`values`**: the oracle filler's text per field label, i.e. the bare city ("Portland").
  - **`goal`**: one of 4 paraphrases, e.g. "Find one-way flights from Portland, Maine to Birmingham, UK. Stop when matching flight options are visible. Do not book anything."
- City pairs, about 15:
  - Portland ME/OR; London UK/ON; San José CR/CA; Birmingham UK/AL; Santiago CL/ES/CU;
  - Sydney AU/NS; Manchester UK/NH; Córdoba AR/ES; Valencia ES/VE; Kingston JM/ON;
  - Paris FR/TX; Newcastle UK/AU; Georgetown GY/Penang; Victoria BC/Seychelles.
- `tests/test_bench_spec.py`:
  - the spec is deterministic per seed;
  - a lookalike is always present;
  - the correct position is spread across seeds;
  - labels and option values are unique;
  - the goal matches a template;
  - no accept code appears outside the suggestion lists.

### 4. The page (`bench/pages/airport.mjs`)
- **Pure core**, with no DOM access at import:
  - `init(page)`, `actions(state)`, `step(state, a)`, `view(state)`;
  - `goal(state, accept)`, `dist(state, accept)`, `label(state, candidates, accept)`.
- Learn (BFS): the states form a graph and every action costs 1, so breadth-first search finds the fewest remaining actions. BFS visits states in order of distance, so the first time it reaches a goal state is the shortest path. Memoize by a state key: the graph is small, but `label()` asks about many candidates.
- **`mount(page, root)`**:
  - Renders once, then updates in place: inputs persist, and only the listbox and results containers are rebuilt.
  - Binds each control to its action in a `WeakMap<Element, descriptor>`.
  - Installs `window.__bench = {label, check, tick, goal, phase}`. Every method catches its own errors and returns `{error}`.
- **Descriptors:**
  - text field → `{click: open(f), fill: type(f)}`. The browser's fill is a click and then input, so fill is labelled as open, then type.
  - select → matched by option `value`.
  - radio, button, option → click.
- **Page rules.** Each one prevents a real harness behaviour:
  - Listen only to `click`, `input` and `change`. Fill sends a Meta+A keydown, and focus/blur handlers would be hidden transitions the oracle doesn't simulate.
  - Every button has `type="button"`. No form submits, links, hash or pushState: the URL is part of the model's input.
  - Everything is in normal flow and fits 1120×780. Off-viewport elements are dropped from the snapshot, and overlays make `act` reject "covered" targets forever.
  - No timers, `Date`, `Intl`, animations or transitions.
  - A WAIT with nothing pending must not touch the DOM, because the fingerprint includes node ids and rects.
  - Loading is visible ("Loading airports…", "Searching flights…"); otherwise WAIT is a guess.
  - No hidden text inside controls, no `aria-selected` on suggestions, no `aria-pressed` (the snapshot doesn't read it), and no button `value` attribute (it becomes the accessible name).
  - Never touch `window.__jevFast`; it is the snapshot's reserved cache.
- **Labels** (distance = actions until "goal met and DONE chosen"):
  - `progress`: distance drops. This is the only accepted label.
  - `neutral`: no change in distance, or the state is unchanged.
  - `regress`: distance rises.
  - `irreversible`: Book. It takes precedence over regress.
  - `invalid`: TYPE_TEXT into a field with no task value, which the helper would refuse.
  - `false_done`, `false_blocked`.
  - `unknown`: an unbound element. This must never happen.
  - WAIT is progress only if a tick shortens the path. Scroll must never appear.
- **Node tests** (`bench/pages/airport.test.mjs`): `tests/test_bench_pages.py` writes specs for seeds 0–49, runs `node --test`, and skips with a reason if `node` isn't on PATH. Asserts:
  - the oracle reaches the goal on every seed;
  - every reachable non-terminal state has at least one progress action;
  - distance drops by exactly 1 along the oracle path;
  - Book is irreversible;
  - equal `view()` means equal labels;
  - `label()` doesn't mutate state;
  - a delay of k means exactly k loading views.

### 5. Serve and browse (`bench/server.py`, `bench/chrome.py`, `bench/smoke.py`)
- **server.py**: stdlib `ThreadingHTTPServer` on a fixed `127.0.0.1:8777` (fail if busy).
  - `/t/<sha256("airport:<seed>")[:10]>` returns a shell page with a static title and an inline module script `mount(<page spec>)`, with `</` escaped.
  - `.mjs` is served as `text/javascript`.
  - Why a fixed port and a deterministic token: the URL is inside every request body, so a random port would change the bodies between runs.
- **chrome.py**:
  - Launch: `restart_daemon()`, then headless Chrome with a temp profile and `--remote-debugging-port=0`. Read `DevToolsActivePort` and set `BU_CDP_WS`.
  - Assert `browser_harness.helpers.NAME == "s1bench"`.
  - Flags:
    - `--use-mock-keychain --password-store=basic`
    - `--disable-background-timer-throttling --disable-renderer-backgrounding --disable-backgrounding-occluded-windows`
    - `--no-first-run --no-default-browser-check --disable-extensions --disable-component-update --disable-sync --lang=en-US`
  - Teardown order: `agent.close` → `restart_daemon` → kill Chrome → delete the profile.
- **smoke.py**: a script in the style of check_guards, with no model calls. For seeds 0–4 it checks:
  - `check()`: the snapshot's candidates equal the state machine's actions plus WAIT, with no unknown labels;
  - no scroll controls appear;
  - `elementFromPoint` lands inside every candidate;
  - `visibilityState` and observe latency after a combobox fill;
  - fill, select, radio, option and WAIT each change hidden state exactly as `step` predicts;
  - the first observation contains no accept codes and none of the words "correct", "answer" or "seed".

### 6. Collect (`bench/run.py`, `bench/policies.py`, `bench/wire.py`)
- **`run.py`** builds `Agent(url, spec.goal)`, sets the three hooks, and iterates `agent.run()`.
  - It adds a bench action cap of 2 × oracle path + 6, with outcome `budget`, because WAIT is exempt from the agent's no-progress stop.
- **Oracle calls** use raw `browser.call("Runtime.evaluate", …)`; a JS exception raises `RuntimeError`.
  - Gotcha: `Browser.evaluate` turns every exception into `StalePage`, which the agent's tick silently retries. That would mean a lost WAIT tick or an endless decide loop.
- **`decide`** labels the observed page, writes a record, then asks the policy. It returns a complete decision dict: `choice`, `probabilities` including the choice, `confidence`, `latency_ms`, `operation`, `target`, `usage`, `model`.
- **`policies.py`**: every way to choose.
  - `oracle`: uniform over progress actions, seeded.
  - `epsilon`: 0.3 chance of a random neutral or regress step.
  - `random`, `lexical`: goal-word overlap with labels.
  - HTTP contenders (step 7).
- **`write_text`** is the oracle filler: label → value. With no value it raises the real helper's exact error, "Text helper returned no valid field value; nothing typed."
- **`after_action`** calls `__bench.tick()` on WAIT and logs the distance afterwards.
- **`wire.py`** defines the record: `{id, seed, policy, step, goal, observation(url, title, text, actions, scroll), history(action, kind, text, page_changed), candidates{action_id: {operation, target, label}}, phase, distance, body_sha256}`.
  - Body hash = sha256 of `json.dumps({**body, "model": ""}, ensure_ascii=False, separators=(",", ":"))`, which is what httpx sends.
  - Gotcha: never sort keys. Key order is part of the model's input.
  - Dedupe on (body hash, label-vector hash).
  - `manifest.json` records commit and dirty flag, source hashes (pattern at `scripts/measure_flights.py:26-29`), Chrome version (`:66`), seeds and ε.
- **Output**: `datasets/airport/m1.jsonl` plus `manifest.json`, from seeds 0–19 with one oracle and one ε rollout each (about 400–500 unique states).
- **Tests**: record building on fake pages, and the hash recomputes from stored fields via `build_request`.

### 7. Replay (`bench/replay.py`)
- **Contenders**, each with explicit endpoint, model and key (never read from env):
  - `random` and `lexical` (offline);
  - `jev-classifier`: https://classifier.dev, `jev-latest`, key from the keychain as in `run_classifier.sh:16`, 60 s timeout;
  - `decider-4b`: local URL, 180 s timeout;
  - `jevk5`: optional, try `--limit 5`.
- **Per record**: rebuild with `build_request`, refuse if the hash differs, set the model, `post_json`, then `parse_answers`.
  - An invalid response is logged as a row.
  - A network error stops the run; it can resume later.
- **Output**: append-only `artifacts/bench/replay/<contender>.jsonl`, resumable on (record_id, contender, variant="original").
- **Flags**: `--seeds`, `--limit`, `--dry-run` (request count and chars/4 token estimate), `--max-input-tokens`.
- **Tests** use a monkeypatched `post_json` and cover resume, hash-mismatch refusal and invalid rows.

### 8. Score (`bench/score.py`, pure Python)
- **Replay**, on identical states:
  - step accuracy with a 95% CI (cluster bootstrap over seeds, seeded);
  - error mix;
  - accepted mass: the sum of P(op)·P(target|op) over progress actions, from `raw_answers`;
  - accuracy per phase; the suggestions phase is the lookalike test.
  - For each confidence signal (the model's reported `confidence` and joint p): AUROC, AURC, coverage at ≤5% and ≤10% risk, Brier, and a risk–coverage CSV.
- Learn (rank-based AUROC): AUROC is the chance that a random correct step has higher confidence than a random wrong one. Sort once and sum the ranks (Mann–Whitney) in O(n log n) instead of comparing all pairs in O(n²). Ties count ½.
- **Closed loop**:
  - success rate;
  - a paired 2×2 table per seed for each pair of contenders (M1: Jev × decider);
  - counts of booked, false DONE and budget outcomes;
  - actions and decisions per episode.
- **Speed and cost**: median and p90 latency, input tokens per decision.
- **`--out results/bench/m1`** writes the table and CSVs and copies exactly the logs it scored, so claims match raw evidence (AGENTS.md).
- **`tests/test_bench_score.py`**: AUROC for perfect, reversed and tied cases; AURC; coverage@risk; bootstrap determinism.

### 9. Closed loop (`bench/run.py closed`)
- Same runner.
- **Policy**: a contender (label, then build/post/parse).
- **Text**: the oracle filler, or production `field_text` with `--text mercury` (run under `uv run --env-file .env`).
- **Outcome**: success = DONE while the goal holds. Also log whether the goal was ever reached, booked, false DONE, budget, and harness error.
  - After a harness error, start a fresh episode. Never re-run a step on the same tab.
- **Offline check**: `--contender lexical --seeds 0-4`.

### 10. Docs and config
- `REQUIREMENTS.md`:
  - fix "Why this is new" (multi-step web benchmarks and escalating System One loops already exist; the gap is measuring the handoff signal);
  - oracle function plus dataset instead of hand-written JSON;
  - WAIT-driven timing;
  - oracle filler plus Mercury check;
  - label definitions and M1 metrics.
- `bench/README.md`: reproduce steps.
- `AGENTS.md`: one line on the bench-only filler, and add `node --check bench/pages/airport.mjs` to the Checks line.
- `pyproject.toml`: add `pythonpath = ["."]` under pytest.

## Files

- **Modified**:
  - `jev_ultrafast/model.py`, `jev_ultrafast/agent.py`, `tests/test_agent.py`
  - `pyproject.toml`, `REQUIREMENTS.md`, `AGENTS.md`
- **New code**:
  - `bench/{__init__,airport,server,chrome,smoke,run,policies,wire,replay,score}.py`
  - `bench/pages/airport{,.test}.mjs`, `bench/README.md`
- **New tests**: `tests/test_bench_{spec,pages,wire,replay,score}.py`
- **Generated**:
  - `datasets/airport/{m1.jsonl,manifest.json}` (tracked)
  - `artifacts/bench/**` (ignored)
  - `results/bench/m1/**` (tracked; written by `score --out`)

## Verification

Offline (I run these):

```
uv run ruff check . && uv run pytest && node --check jev_ultrafast/static/app.js \
  && node --check jev_ultrafast/snapshot.js && node --check bench/pages/airport.mjs && uv build
uv run python -m bench.smoke --seeds 0-4
uv run python -m bench.run collect --seeds 0-19      # run twice: body hashes must match
uv run python -m bench.replay --contender random
uv run python -m bench.replay --contender lexical
uv run python -m bench.replay --contender jev-classifier --dry-run
uv run python -m bench.run closed --contender lexical --seeds 0-4
uv run python -m bench.score artifacts/bench
```

Pass criteria:
- all checks green;
- oracle succeeds 20/20;
- two collections give identical hashes;
- random scores about chance;
- lexical accuracy in the suggestions phase is clearly below 100%. If lookalikes are solvable by string match, fix the spec before any paid run.

Live (you run these; your normal Chrome is untouched):
1. `uv run python -m bench.replay --contender jev-classifier --limit 5` as a sanity check, then again without `--limit`.
2. Start decider's server, then `uv run python -m bench.replay --contender decider-4b --seeds 0-9` (about 220 calls × 12 s ≈ 45 min).
3. Closed loop:
   - `uv run python -m bench.run closed --contender jev-classifier --seeds 0-19`
   - the same with `--contender decider-4b --seeds 0-9`
   - Mercury check: `uv run --env-file .env python -m bench.run closed --contender jev-classifier --text mercury --seeds 0-2`
4. `uv run python -m bench.score --out results/bench/m1`

## Budget (M1)

- **Jev**: about 450 replay calls plus about 300 closed-loop calls, each around 2k input tokens. That's about 1.5M tokens, roughly $0.06 at TypeSafe's $0.042 per million (check classifier.dev's rate), well inside $5.
- **Mercury**: about 10 calls, under $0.001.
- **decider**: free; about 45 min of replay plus about 30 min of closed loop.

## After M1 (planned after we see the numbers)

- **M2**:
  - retest, shuffle, relabel and inject variants on replay;
  - oracle-as-LLM escalation in the closed loop;
  - fold closed-loop states into the replay set;
  - date picker, stop-before-pay checkout and destructive-toggle tasks;
  - extract a shared `runtime.mjs`;
  - McNemar and ECE once n grows.
- **M3**: interruption modal (with `inert`), pagination, form validation, a MiniWoB++ subset, a REAL sanity check, and live Flights labelled as not reproducible.
- **M4**: results table, curves, README and write-up.
