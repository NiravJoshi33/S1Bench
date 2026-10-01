# S1Bench M1: implementation plan (airport autocomplete, harness through scoring)

> Written against the jev-ultrafast checkout: `bench/` is now `s1bench/` and `jev_ultrafast/` is now `s1bench/harness/`. The order to build in is [003-build-order.md](003-build-order.md); this doc is the detail each chunk follows.

## Context

S1Bench (REQUIREMENTS.md) measures how well System One models (Jev, decider-4b, jevk5) handle multi-step browser tasks. It also measures whether their confidence flags the steps they get wrong, which is what an agent needs to know before handing a step to an LLM.

- **Design of record:** `docs/plans/001-m1-design.md`, agreed in the previous session. It covers design rules 1–6, page rules, the city list, the goal paraphrases and the budget.
- **What this plan adds:**
  - the build order;
  - a precise state machine, which the doc left open;
  - the orchestration details;
  - 16 corrections. I checked the doc line by line against the current code and browser_harness 0.1.13, and those gaps would break the build.
- **Scope:** M1 only (build M1, look at the numbers, then plan M2), as agreed.

Pipeline: seeded local page → JS state machine labels every candidate action → replay dataset → model runs → scored table.

Four commands:
- `bench.run collect` builds the dataset with no model calls.
- `bench.replay` sends recorded requests to one model, with no browser.
- `bench.run closed` lets a model drive the page.
- `bench.score` writes the table and the risk–coverage CSVs.

No new dependencies, no commits, no paid calls from me.

## Changes to docs/plans/001-m1-design.md, with the reasons

1. **Distances come from a lookup table over simplified states, not a fresh BFS per candidate.**
   - Problem: the doc says the graph is small (L114). It isn't. Results remember the searched query, and the currency setting multiplies states, so about 4×10⁵ states are reachable (about 5×10⁶ with Swap).
   - At about 20 candidates per step, BFS would take seconds to minutes per step. It would also hit browser_harness's 5 s call timeout (`helpers.py:42`).
   - Why: only distance matters. States that always have the same distance can share one key, which leaves about 2k keys. The table is built once per episode (about 10 ms), then each lookup is O(1).
   - A Node test checks the table against brute-force BFS on small specs.
2. **Test "equal view ⇒ equal progress set", not "equal labels" (L146).**
   - The number of loading ticks left is hidden: "Loading…" looks the same with 1 or 2 left. From those two states, a trip click is neutral in one and regress in the other.
   - Keep full label equality only for views with no timer running.
3. **One DOM event per control type (L124).** Text inputs fire `change` when they lose focus, and the executor fires both `input` and `change` on selects (`browser.py:156-157`).
   - `click` for buttons, options, radios and the text field itself;
   - `input` for text fields;
   - `change` for selects only.
4. **Python gives the oracle one fill text per candidate, looked up by the snapshot's own label.**
   - This is the same lookup `write_text` uses, so labelling and typing can't disagree.
   - Labels must be plain text. `snapshot.js:20-21` joins child nodes with spaces, so `<label>Where <b>from</b>?` becomes "Where  from ?" and the lookup would miss.
5. **More confidence signals (L211).**
   - A lookalike mistake is a target-head error made under a confident CLICK, so the operation `confidence` alone can't catch it.
   - Score four signals: op confidence, target confidence, min(op, target) and joint p = P(op)·P(target|op).
6. **Force `BU_NAME=s1bench` (L82)** instead of `setdefault`, which lets an exported BU_NAME win. Assert `helpers.NAME` at launch.
7. **Oracle failures raise their own `BenchError(Exception)` (L174).** Today they'd raise RuntimeError, which you can't tell apart from `post_json` and `cdp()` errors. Hooks must never raise `StalePage`, because the agent's `tick` swallows it and loops.
8. **Episode outcome classes and a stale-retry canary** (details in step 6).
9. **Chrome safety.**
   - Add `--headless --user-data-dir --remote-debugging-port=0 --hide-scrollbars --disable-background-networking` to the flags.
   - A pidfile lets a crashed run clean up after itself.
   - Assert the daemon kind is `cdp` and the user agent says `HeadlessChrome`, so it can never drive your real Chrome.
   - `restart_daemon()` before launch is mandatory. `ensure_daemon` reuses any healthy daemon with the same name (`admin.py:527-534`), and the daemon is detached (`_ipc.py:80`).
10. **Collect seeds 0–49, not 0–19 (L189).**
    - 20 seeds give only about 60–80 suggestion-phase records, which is a ±11-point CI on the lookalike number. Collection is free, and a Jev replay of all 50 costs about $0.3.
    - decider replays seeds 0–9 first (about 45 min).
11. **Store the dataset as deterministic gzip** (`m1.jsonl.gz`, `mtime=0`, about 1 MB instead of about 8 MB).
    - Record ids are content hashes, so resume keys survive a re-collection.
    - The same request body with different labels would mean hidden state. Count these as conflicts (expect 0) rather than keeping both.
12. **Replay row statuses.**
    - `malformed` (not `invalid`, which is already a label name) counts as wrong in accuracy, is left out of AUROC, and is always escalated on the curve.
    - HTTP 400/422 is logged as a `rejected` row. 401/402/403, 429, 5xx and connection errors stop the run so it can resume later.
    - Rows don't copy the request body.
13. **`parse_answers` works on a copy.** Today `model.py:124-125` writes synthesized heads into the provider's `result`.
14. **Token estimate is chars × 0.38, not chars/4 (L202).** That's the measured rate in both classifier.dev runs (11,609-char body → 4,185 input tokens).
15. **Lexical pass criterion, fixed in advance (L276).**
    - Each goal names its cities in one of four forms: verbatim, abbrev, country-alias or airport. At least 60% of seeds use abbrev or country-alias (for example "Maine" in the goal vs "ME" in the option).
    - Gate: lexical option-only accuracy ≤ 0.6, with ties going to the first option in DOM order. If it's higher, fix the spec before any paid run.
16. **The shell page imports `/pages/airport.mjs` by absolute path.** A `./` path would resolve under `/t/`.

## Build order (each step testable on its own; steps 0–8 need no paid API)

### 0. Baseline
- Run `uv sync` and the checks.
- Expect exactly one failure, `tests/test_agent.py:96`. Commit 4f4ed0f trims single-option heads, so `type_text_target` is no longer posted.

### 1. Split the model call (`jev_ultrafast/model.py`)
- **`build_request(page, goal, history, model=None) -> (body, meta)`:** today's L82–122. `meta` holds operations, targets, controls and single heads.
- **`parse_answers(result, meta)`:** L124–151, working on a copy.
- **`choose()`:** build → `post_json` → parse. The return shape stays the same, and the timer still covers only the POST.
- **`post_json(url, key, body, timeout=httpx.USE_CLIENT_DEFAULT)`.** Gotcha: `timeout=None` means *no timeout* in httpx.
- **Tests:**
  - L96 expects `{"operation","click_target"}`, and the synthesized `type_text_target` has p = 1.0;
  - golden test: the `build_request` body equals what `choose()` posts;
  - the timeout is passed through;
  - `result` is not mutated.

### 2. Agent hooks (`jev_ultrafast/agent.py`)
- Add class attributes `decide = write_text = after_action = None` and keyword-only constructor arguments. Resolve them at call time:
  - `(self.decide or choose)(…)` at L77;
  - `(self.write_text or field_text)(context)` at L113.
  - Why: a default argument binds at import. That would break the tests that monkeypatch `loop.field_text`, and the `Agent.__new__` fixture never runs `__init__`.
- Build the full history entry **before** `browser.act` (L117). After `act`: set the times, append the entry, call `after_action(state)`, then observe (L142).
  - Why: today a missing decision key raises after the click is sent, so the action runs but is never logged. AGENTS.md: log execution before observing.
- **Tests:**
  - call order is act → after_action (entry already present) → observe;
  - a decision without `usage` raises before `act`;
  - all existing tests pass unchanged.

### 3. Package and task spec (`bench/__init__.py`, `bench/airport.py`)
- **`__init__`** sets `os.environ` BU_NAME=s1bench, BH_TAB_MARKER=0 and BH_TELEMETRY=0 before anything imports `jev_ultrafast`.
- **`spec(seed) -> {goal, page, accept, values, form}`** with `random.Random(f"airport:{seed}")`. String seeds are stable across processes; never use `hash()`, which PYTHONHASHSEED randomises.
  - **`page`** (presentation only):
    - plain-text, unique labels with no `→`, since `model.py:62` splits on it;
    - control order;
    - trip control: radios or a select, usually defaulting to round trip;
    - 2–8 real suggestions per city, with the correct one's position spread across seeds;
    - neutral values (`o1…`, `t1/t2`, `c1…`);
    - delays kS and kR in {0, 1, 2};
    - 0–3 distractors: Promo code, Swap, currency;
    - result rows, each with a Book button.
  - **`accept`:** codes per side (city-level seeds accept every metro airport plus "All airports") and one-way.
  - **`values`:** field label → bare city.
  - **`goal`:** one of 4 paraphrases. It never names a code.
- **City table:** the 14 pairs from the doc (L98–101), stored in NFC.
- **`tests/test_bench_spec.py`:**
  - determinism, plus a golden hash for seed 0 (catches changes to `random` across Python versions);
  - a lookalike is always present;
  - the correct position is spread across seeds;
  - labels and values are unique;
  - the goal matches a template;
  - no accept code appears outside the suggestion lists;
  - the form shares hold, and the static lexical check passes.

### 4. Page and oracle (`bench/pages/airport.mjs`, pure core plus `mount`)
State and transitions. "close" means `open = null, left = 0`, which cancels a pending list, so no pending work is ever invisible.
```
state: trip 'round'|'oneway' · cur · promo · f[0..1] {text, pick|null} (picked ⇒ text = option label)
       open null|0|1 · left 0..kS · res null | error(miss) | loading(q,left) | loaded(q)   q={from,to,trip}
       booked null|row
open(f)    open===f → no-op; else close; f unpicked && text → open=f, left=kS
type(f,x)  x===text && unpicked → open(f); else f={text:x,pick:null}, open=f, left=kS
fill(f,x)  type(open(s,f), f, x)            # the browser's fill = click, then input
pick(f,o)  only while open===f && left===0: f={label(o), o}; close
trip/swap/cur/promo  apply; close
search     close; unpicked side → error; q equals res.q → results unchanged; else kR ? loading(q,kR) : loaded(q)
book(r)    booked=r (absorbing, dist ∞)
wait       nothing pending → same object, no DOM write; else list.left−1 and res.left−1
goal       !booked && res loaded && q.from∈accept.from && q.to∈accept.to && q.trip==='oneway'
```
- **Free-text matching**, so production text runs work:
  - normalise with NFKD, strip accents, lowercase;
  - drop stopwords;
  - every remaining token must prefix one of the option's keys: city, region and its abbreviation, country and its aliases, airport-name words, IATA code.
  - "Portland" shows all the lookalikes, and "Portland, Maine" shows only PWM.
- **Visible results.** The loading line and the results header both name the searched query, so DONE can be judged from the page alone.
- **Distances.**
  - The key is `(trip, F0, F1, open, left, R)`.
  - F is empty, typed(text), or picked, and a pick is classed only by acceptance: from-ok, to-ok or neither.
  - R is none/wrong, loading-correct(k) or loaded-correct.
  - Currency, promo text and error messages are dropped from the key.
  - Build it once per episode: step forward from the start state, keeping one real state per key and using the real `step`. Then run one reverse BFS from the goal keys. Extend it lazily if a new key appears.
  - Learn (reverse BFS): when you'll ask "how far is X from the goal?" many times on one fixed graph, run BFS backwards from all goal states at once. One pass gives every state's distance. Merging states under a key is safe only if they always have equal distance, which the brute-force test proves.
- **Labels.**
  - progress: distance drops by 1.
  - neutral: no change, including no-ops.
  - regress: distance rises.
  - irreversible: Book.
  - invalid: TYPE_TEXT with no filler value.
  - false_done, false_blocked.
  - unknown: an unbound element or scroll. This aborts the episode as a harness error.
  - Each candidate also stores `delta` and `noop`.
- **`mount`:**
  - `view(s)` returns a render key per region: fields, each list, trip, currency, promo, results.
  - A region is rebuilt only when its key changes, and input values are compared before writing. That way no-op actions leave node ids and rects alone, and `page_changed` stays honest.
  - A `WeakMap<Element, descriptor>` binds each control to its action.
  - It installs `window.__bench = {label, status, tick, check, phase}`. Each method catches its own errors and returns `{error}`.
  - `window.__jevFast` is read-only here.
- **Page rules:** the doc's rules at L123–131, plus:
  - `<div role="option">` (an `<li>` exposes `value` "0");
  - no answer information in title, aria-label, alt, placeholder, aria-selected/checked, button `value`, sr-only text or the URL;
  - the module is ASCII, served as utf-8;
  - a two-column layout: in the worst case (8 options plus 4 rows), each column is about 520 px tall.
- **`bench/pages/airport.test.mjs`** reads the specs from a path in an env var. It asserts:
  - the oracle reaches the goal on every seed;
  - every reachable non-booked state has a progress action;
  - distance drops by exactly 1 along the oracle path;
  - Book is irreversible;
  - equal view ⇒ equal progress set;
  - `label()` doesn't mutate state (states deep-frozen);
  - a delay of k gives exactly k loading views;
  - the table equals brute-force BFS on reduced specs;
  - no-ops leave the view keys equal.
- **`tests/test_bench_pages.py`** writes specs for seeds 0–49 and runs `node --test`. It skips with a reason if `node` is missing.

### 5. Serve, launch, smoke (`bench/server.py`, `bench/chrome.py`, `bench/smoke.py`, `bench/oracle.py`)
- **server:**
  - stdlib `ThreadingHTTPServer` in a thread on fixed `127.0.0.1:8777`, failing if busy;
  - `/t/<sha256("airport:<seed>")[:10]>` returns the shell page with a static title, CSS and `mount(<page spec>)`, with `</` escaped;
  - `/pages/airport.mjs` is served as `text/javascript`.
  - Why fixed: the URL is inside every request body.
- **chrome:**
  - Launch: kill any stale pid from `artifacts/bench/chrome.json` whose command line holds its profile, then `restart_daemon()`, start headless Chrome with a temp profile and the flags (doc L159-161 plus item 9), read `DevToolsActivePort`, and set `BU_CDP_WS`.
  - Teardown in `finally`, and on SIGTERM/SIGHUP: agent.close → restart_daemon → killpg TERM, then KILL → delete the profile → unset → stop the server.
- **oracle:**
  - raw `browser.call("Runtime.evaluate", …, awaitPromise=False, returnByValue=True)`;
  - `exceptionDetails` or `{error}` raises `BenchError`;
  - never `Browser.evaluate`, which turns every exception into StalePage.
- **smoke**, seeds 0–4, no model calls. It checks:
  - `check()` equals the machine's actions plus WAIT;
  - no scroll controls;
  - `elementFromPoint` lands inside every candidate;
  - each of fill, select, radio, option and WAIT changes state exactly as `step` says;
  - `visibilityState` and the observe latency after a combobox fill;
  - no accept code and no "correct", "answer" or "seed" in the first observation;
  - worst case (goal reached, refill the origin, then kS WAITs): `scrollHeight ≤ 780`;
  - the headless user agent.

### 6. Collect (`bench/run.py`, `bench/policies.py`, `bench/wire.py`)
- **Episode:**
  1. `Agent(url, goal, decide=…, write_text=…, after_action=…)`.
  2. `oracle.status()`: `__bench` is present, `check()` passes, there is no scroll and dist0 is finite. The cap is 2·dist0 + 6 actions.
- **`decide(page, goal, history)`:**
  1. Assert `page is last_page`, then `n_decide += 1`.
  2. One evaluate runs `label(candidates, texts, accept)`, which also runs `check()`.
  3. `build_request` → body hash.
  4. Write the record.
  5. The policy picks.
  6. Return a complete decision dict: choice, probabilities (including the choice), confidence, latency_ms, operation, target, usage and model.
- **`write_text`** is the oracle filler. With no value it raises the helper's exact message, "Text helper returned no valid field value; nothing typed."
- **`after_action`:**
  - `n_acted += 1`;
  - `tick()` on WAIT;
  - `status()` goes into `history[-1]["bench"]`. That's safe because `build_request` reads only four history keys.
- **Stale-retry canary.**
  - `n_decide − n_acted` must be 0, or 1 when the run ends on DONE/BLOCKED. Any other value is a harness error.
  - Both real Jev runs had 18 decisions for 10 actions, so silent retries do happen.
- **Outcomes, first match wins:**
  - harness_error;
  - transport_error (excluded from rates; rerun);
  - booked;
  - success (DONE while the goal holds);
  - false_done;
  - model_blocked;
  - stuck (the agent's 3-strike no-progress stop);
  - text_refused;
  - malformed;
  - budget.
  - Also log `goal_seen`.
- **policies:**
  - `oracle`: uniform over progress actions, seeded per (seed, policy, rollout).
  - `epsilon`: 0.3 chance of a random neutral or regress action, never an irreversible/invalid/false_* one.
  - `random`, `lexical`.
  - HTTP contenders. Each has an explicit name, URL, model, key source and timeout; nothing is read from `TYPESAFE_*`.
    - `jev-classifier`: keychain as in `run_classifier.sh:16`, 60 s.
    - `decider-4b`: `http://127.0.0.1:8767`, 180 s.
    - `custom`: `--url/--model/--key-env` for anyone else's model.
- **Record** (`wire.py`):
  - `{id, seed, rollout, step, goal, observation{url,title,text,actions (rects stripped),scroll}, history[last 10: action,kind,text,page_changed], candidates{id:{operation,target,label,delta,noop}}, phase, distance, form, body_sha256}`.
  - The hash is taken over `json.dumps({**body,"model":""}, ensure_ascii=False, separators=(",",":"), allow_nan=False)`, which is what httpx 0.28.1 sends. Never sort keys: key order is part of the model's input.
- **Output:**
  - `datasets/airport/m1.jsonl.gz`, deduped by id, with conflicts counted;
  - `manifest.json`: commit and dirty flag, source hashes (pattern at `scripts/measure_flights.py:26-29`), Chrome version (`:66`), Python version, seeds, ε, counts, stale and conflict totals;
  - `--out DIR` for the determinism check.
- **Tests:** records built on fake pages; the hash recomputes via `build_request`; ids are stable; dedupe and conflict counting; outcome classification as a pure function.

### 7. Replay (`bench/replay.py`)
- **Per record:**
  - rebuild with `build_request`, and refuse if the hash differs;
  - set the model, then `post_json` → `parse_answers`;
  - append a row with the status (ok, malformed or rejected), the answers, usage and latency.
- **Output:** `artifacts/bench/replay/<contender>.jsonl`, append-only, resumable on (record_id, contender, variant="original").
- **Flags:** `--seeds`, `--limit`, `--dry-run` (request count and the chars × 0.38 token estimate), `--max-input-tokens`.
- **Tests** (monkeypatched `post_json`): resume, hash-mismatch refusal, malformed and rejected rows, and 402/5xx stopping the run.

### 8. Score (`bench/score.py`, pure Python)
- **Replay, on identical states:**
  - step accuracy with a 95% CI from a seeded cluster bootstrap over seeds;
  - error mix;
  - accuracy per phase (the suggestions phase is the lookalike test);
  - option-pick accuracy given CLICK on an option;
  - accepted mass;
  - for each of the four signals: AUROC, AURC, coverage at ≤5% and ≤10% risk, Brier, and a risk–coverage CSV;
  - the chance baseline.
- **Closed loop:**
  - success rate;
  - a paired 2×2 per seed for each contender pair;
  - outcome counts;
  - actions and decisions per episode.
- **Speed and cost:** median and p90 latency, input tokens per decision.
- **`--out results/bench/m1`** writes `table.md`, the CSVs, and gzipped copies of exactly the logs it scored. That keeps claims matched to raw evidence (AGENTS.md).
- **`tests/test_bench_score.py`:** AUROC for perfect, reversed and tied cases; AURC; coverage@risk; bootstrap determinism; malformed handling.
- I'll offer you first go at `auroc()` (Mann–Whitney ranks, about 10 lines) when we get there.

### 9. Closed loop (`bench/run.py closed`)
- Same runner, with a contender as the policy.
- Text comes from the oracle filler, or from production `field_text` with `--text mercury` (run under `uv run --env-file .env`).
- A fresh tab per episode. After a harness error, start a new episode; never re-run a step on the same tab.
- Offline check: `--contender lexical --seeds 0-4`.

### 10. Docs and config
- **`docs/plans/001-m1-design.md`:** fold in the corrections above.
- **`REQUIREMENTS.md`:**
  - "Why this is new" becomes: the gap is measuring the handoff signal;
  - oracle function plus dataset;
  - WAIT-driven timing;
  - oracle filler plus a Mercury check;
  - label definitions and M1 metrics.
- **`bench/README.md`:** reproduce steps, including decider's launch command.
- **`AGENTS.md`:** one line on the bench-only filler (an exception to "TYPE_TEXT invokes the text LLM" and to "no hardcoded field values"). Add `node --check bench/pages/airport.mjs` to the Checks line.
- **`pyproject.toml`:** `pythonpath = ["."]` under pytest.

## Files
- **Modified:** `jev_ultrafast/model.py`, `jev_ultrafast/agent.py`, `tests/test_agent.py`, `pyproject.toml`, `REQUIREMENTS.md`, `AGENTS.md`, `docs/plans/001-m1-design.md`
- **New code:** `bench/{__init__,airport,server,chrome,oracle,smoke,run,policies,wire,replay,score}.py`, `bench/pages/airport{,.test}.mjs`, `bench/README.md`
- **New tests:** `tests/test_bench_{spec,pages,wire,replay,score}.py`
- **Generated:** `datasets/airport/{m1.jsonl.gz,manifest.json}` (tracked), `artifacts/bench/**` (already ignored), `results/bench/m1/**` (tracked)

## Reused as-is
- `action_space`, `validate_choice`, `post_json`, `field_context` and `field_text` from `model.py`
- `Browser` and `fingerprint` from `browser.py`
- the `Agent` loop
- the source-hash and Chrome-version pattern from `scripts/measure_flights.py`
- the script style of `scripts/check_guards.py`
- the keychain read in `run_classifier.sh`
- the httpx `CLIENT`

## Verification
Offline (I run these):
```
uv run ruff check . && uv run pytest && node --check jev_ultrafast/static/app.js \
  && node --check jev_ultrafast/snapshot.js && node --check bench/pages/airport.mjs && uv build
uv run python -m bench.smoke --seeds 0-4
uv run python -m bench.run collect --seeds 0-49 --out artifacts/bench/c1   # and again to c2
uv run python -m bench.replay --contender random && uv run python -m bench.replay --contender lexical
uv run python -m bench.replay --contender jev-classifier --dry-run
uv run python -m bench.run closed --contender lexical --seeds 0-4
uv run python -m bench.score artifacts/bench
```
Pass criteria:
- all checks green;
- smoke passes;
- the oracle succeeds 50/50;
- c1 and c2 are identical after decompression;
- 0 stale retries, 0 conflicts, 0 unknown labels;
- random scores about chance;
- lexical option-only accuracy ≤ 0.6.

Live (you run these; your normal Chrome is untouched):
1. Jev replay with `--limit 5`. Check the real tokens and cost, then run all 50 seeds.
2. Start decider on :8767, then replay `--seeds 0-9` (about 45 min).
3. Closed loop: Jev on seeds 0–19, decider on 0–9, and Mercury on 0–2.
4. `bench.score --out results/bench/m1`.

Budget:
- **Jev:** about 1,500 calls × about 2k input tokens ≈ 3M tokens, roughly $0.15–0.35.
- **Mercury:** about 10 calls.
- **decider:** free, about 70 min in total.

## Needs from you (not blocking the build)
- **decider-4b's launch command and the model name it expects.**
  - It serves on :8767, but the launch command isn't recorded anywhere yet.
  - I'll put the command in `bench/README.md` once you give it to me.
- **jevk5 stays optional.** I'll install it only after you OK it, with an audit first.

## After M1 (planned once we see the numbers)
- **M2:**
  - retest, shuffle, relabel and inject variants on replay;
  - LLM escalation in the closed loop;
  - date picker, checkout and destructive-toggle tasks;
  - a shared `runtime.mjs`.
- **M3 and M4:** as in the doc.
