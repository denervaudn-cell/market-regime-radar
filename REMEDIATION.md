# V5 remediation and V4 feature restoration

Baseline: `pre-revamp-2026-10-19` / `6b1e466d2e475addccbb7e7eed69f2a871f938ce`.
Implementation branch: `codex/radar-revamp`. Evidence date: 2026-10-19.
Status: core remediation and full V4 analytical restoration implemented and locally verified. External real-data delivery, empirical investment-model validation and production rollout remain separate.

The original report is retained as historical evidence. “Implemented” below means an application change with a concrete verification path, not proof of a production deployment or investment efficacy.

| # | Finding | Remediation | Verification |
|---|---|---|---|
| 1 | Competing engines / incorrect modes | One Python engine; three exhaustive strategy identities; compare shares prepared history; old Node imports only proxy | Engine mode/weight tests and actual routed compare test |
| 2 | Synthetic analytics presented as live | Hardcoded outputs removed; explicit seeded mock mode generates inputs only; source/date/kind/seed on calculated responses and exports | Mock provenance/hash, actual API and browser tests |
| 3 | Frozen Risk Bias | Documented 1D/1W/1M research rules calculate signed scores, divergence and contributions; strength is not a probability | Additivity, timing, flat-variance and unavailable-input tests |
| 4 | Positional correlations / stale LIVE | Exact consecutive-session interval joins, minimum samples, dated sources and independent NYSE calendar | No-overlap, missing-session, stale and holiday cases |
| 5 | Same-close lookahead | Per-version availability cutoffs; month-end decision followed by next-session-close execution | Delayed-publication/revision and execution-boundary tests |
| 6 | Missing periods disappear | Complete calendar and ETF-history validation; reject gaps with identified series/date | Missing internal dates and whole-period cases |
| 7 | Incomplete turnover costs | Signed target minus drifted positions on both legs; one-way entry, rebalance and liquidation fees | 40-bps extreme entry, rotating shorts, swapped ranks and drift fixtures |
| 8 | Missing values coerced to zero | Strict numeric observations, positive prices, missing markers rejected before arithmetic | Blank/boolean/NaN/infinity/zero data cases |
| 9 | Invalid parameters trigger work | Single scalar/enum/date/range parser, finite costs preserving zero, duplicate aliases rejected | HTTP tests assert no acquisition on bad requests |
| 10 | Multiple chart owners | One state/render lifecycle; native SVG charts, no Chart.js ownership or duplicate runners | Repeated successful browser runs |
| 11 | Repeated unbounded provider work | Shared immutable snapshot, acquisition coalescing/cache, bounded work slots and result reuse; GET only | Single-flight, cache identity, concurrency and method tests |
| 12 | Old results under new parameters | Immutable request parameters, disabled pending controls, stale-response guards and failure clearing | Browser race/mismatch and success-followed-by-failure tests |
| 13 | Partial month treated as full | Complete execution-to-execution cycles at selected frequency, partial calendar-year labels and elapsed-day accrual | Open-period, calendar-year and endpoint tests |
| 14 | Incorrect Sharpe | Arithmetic cycle excess-return mean / sample deviation × sqrt(52/12/4); typed null for zero variance | Independent alternating-return, frequency-scaling and zero-variance cases |
| 15 | Trading after insolvency | Daily marking; zero terminal NAV; no later trades; unavailable annualized risk statistics after ruin | Leveraged-loss and terminal-state cases |
| 16 | Evaluation shifted by warm-up | Pre-start history retained; missing warm-up fails; requested and effective dates returned | 2020 selection starts first eligible January execution, not 2021 |
| 17 | Wrong short-rank weights | Worst short gets −50%; attribution uses actual signed contribution | Exact rank-weight and leg-P&L tests |
| 18 | Unexplained scoring policy | Versioned shared sector model and documented composite rules with additive factor disclosure and explicit unvalidated status | Formula parity, contribution and timing tests; empirical efficacy/domain interpretation remain unresolved |
| 19 | No acquisition deadlines/cancellation | Fixed-source bounded loader, timeouts, retry budget, cancellation ownership, byte/observation limits | Timeout, cancellation, transient failure and size-limit tests |
| 20 | Cacheable demo failures / no telemetry | No demo fallback; 503/no-store on failures; structured request IDs/outcomes/durations | HTTP error/cache tests; deployed alert delivery still requires production setup |
| 21 | No behavioral gates | Financial/data/market/API suites, real-browser lifecycle tests and pinned CI | Local suite results recorded below; CI has not yet run remotely |
| 22 | Undeclared moving browser/tooling deps | No browser CDN; Python/npm manifests and locks; declared Playwright, uv setup and CI checks | Locked install, lint, browser suite and dependency audits |
| 23 | Contradictory setup and capabilities | New current README, model/data contracts and operational runbook; V4 prose archived | Route/setup checks and documentation review |

## External completion conditions

- The extended data_mesh producer must supply the required real histories and trustworthy availability/revision metadata. The application side is implemented; the shared producer is outside this repository and was not modified.
- The legacy sector model and newly documented regime heuristics require economic review and empirical evaluation. The user requested calculated replacements for former demo panels; these are implemented as explicit research rules, not calibrated probabilities or demonstrated investment efficacy.
- Production routing, approved data entitlements, deployment identity, alert destination and deployed readiness must be verified during rollout. This task does not claim a production release.

## Verification record

The initial core record below predates the full feature restoration. The complete [V4 feature matrix](docs/v4-feature-parity.md) maps restored capabilities; the expansion record follows it.

- `uv sync --locked` and `npm ci`: passed using the committed lockfiles.
- `npm run check`: Ruff lint, formatting (26 Python files) and browser JavaScript syntax checks passed.
- `uv run pytest -q`: **115 passed**. One upstream Starlette TestClient/httpx deprecation warning remains; no failing tests.
- `npm run test:legacy`: **3 passed**.
- `npm run test:ui`: **9 passed** in Chromium, including repeated runs, request races, failure clearing, immutable parameters, inert provider strings, file-mode guidance and mobile layout.
- A separate browser smoke against the actual Python API with an explicitly synthetic local snapshot rendered all three strategies and four charts without JavaScript/CSP errors; mobile layout stayed inside the viewport. This does not validate a real data feed.
- `uv run pip-audit` and `npm audit --audit-level=moderate`: no known vulnerabilities reported for the resolved dependencies on 2026-10-19.
- `git diff --check`: passed. The annotated rollback tag was verified on origin at the baseline commit.

CI configuration is included but has not run remotely. The implementation branch has not been pushed or deployed.

## Full V4 restoration verification — 2026-10-19

- `npm run check`: passed; 35 Python files formatted, Ruff lint and browser JavaScript syntax clean.
- `uv run pytest -q`: **182 passed**, including 69 engine/studies, 20 analytics, 47 data/market, 36 API and 10 mock-source tests. The same upstream Starlette TestClient deprecation warning remains non-failing.
- `npm run test:ui`: **14 passed**; `npm run test:legacy`: **3 passed**.
- Actual Python API browser smoke: all ten analytical families ready, weekly Top-5 comparison, quarterly Top-2, nine robustness variants and four cost scenarios, mock-labelled JSON exports, no JavaScript/CSP errors and no horizontal page overflow at 390px or 1500px.
- Independent formula cases cover annual boundaries, frequency scaling, signed attribution, spread averages, log-return realized volatility, yield spreads, same-date volatility combinations, FX quote orientation, causal historical matches, revision/availability handling and null/partial states.
- Full 62-series mock snapshot is approximately 10.5 MiB and generates in approximately 1.3 seconds locally. Full analytics completes in approximately 2.1 seconds; the bounded study grid completes in under one second on the development machine. These are local observations, not production latency guarantees.
- Longest supported mock weekly Top-5 comparison remains within the 2 MiB API result limit; chart sampling preserves extrema while numerical statistics use all daily marks.
- `uv run pip-audit`, `npm audit --audit-level=moderate` and `git diff --check`: passed; no known dependency vulnerabilities reported.

The preview now selects mock inputs explicitly. No shared producer, database, production deployment or remote branch was changed by the restoration. The rollback tag remains intact.
