# V5 remediation of the V4 audit

Baseline: `pre-revamp-2026-10-19` / `6b1e466d2e475addccbb7e7eed69f2a871f938ce`.
Implementation branch: `codex/radar-revamp`. Evidence date: 2026-10-19.
Status: application remediation and local verification complete. External data delivery, investment-model validation and production rollout remain outstanding as specified below.

The original report is retained as historical evidence. “Implemented” below means an application change with a concrete verification path, not proof of a production deployment or investment efficacy.

| # | Finding | Remediation | Verification |
|---|---|---|---|
| 1 | Competing engines / incorrect modes | One Python engine; three exhaustive strategy identities; compare shares prepared history; old Node imports only proxy | Engine mode/weight tests and actual routed compare test |
| 2 | Synthetic analytics presented as live | Fixture UI removed; source/date/status on observations; unavailable unsupported panels; holdings only from actual results | Browser market/failed-run tests, data coverage cases |
| 3 | Frozen Risk Bias | Remove misleading neutral-50 display and placeholder formula; show observed inputs and explicit model-review state | Market and browser unavailable-state tests; directional composite awaits domain review |
| 4 | Positional correlations / stale LIVE | Exact consecutive-session interval joins, minimum samples, dated sources and independent NYSE calendar | No-overlap, missing-session, stale and holiday cases |
| 5 | Same-close lookahead | Per-version availability cutoffs; month-end decision followed by next-session-close execution | Delayed-publication/revision and execution-boundary tests |
| 6 | Missing periods disappear | Complete calendar and ETF-history validation; reject gaps with identified series/date | Missing internal dates and whole-period cases |
| 7 | Incomplete turnover costs | Signed target minus drifted positions on both legs; one-way entry, rebalance and liquidation fees | 40-bps extreme entry, rotating shorts, swapped ranks and drift fixtures |
| 8 | Missing values coerced to zero | Strict numeric observations, positive prices, missing markers rejected before arithmetic | Blank/boolean/NaN/infinity/zero data cases |
| 9 | Invalid parameters trigger work | Single scalar/enum/date/range parser, finite costs preserving zero, duplicate aliases rejected | HTTP tests assert no acquisition on bad requests |
| 10 | Multiple chart owners | One state/render lifecycle; native SVG charts, no Chart.js ownership or duplicate runners | Repeated successful browser runs |
| 11 | Repeated unbounded provider work | Shared immutable snapshot, acquisition coalescing/cache, bounded work slots and result reuse; GET only | Single-flight, cache identity, concurrency and method tests |
| 12 | Old results under new parameters | Immutable request parameters, disabled pending controls, stale-response guards and failure clearing | Browser race/mismatch and success-followed-by-failure tests |
| 13 | Partial month treated as full | Only complete execution-to-execution monthly cycles; explicit excluded partial endpoint and elapsed-day accrual | Open-month and endpoint tests |
| 14 | Incorrect Sharpe | Arithmetic monthly excess-return mean / sample deviation × sqrt(12); typed null for zero variance | Independently known alternating-return and zero-variance cases |
| 15 | Trading after insolvency | Daily marking; zero terminal NAV; no later trades; unavailable annualized risk statistics after ruin | Leveraged-loss and terminal-state cases |
| 16 | Evaluation shifted by warm-up | Pre-start history retained; missing warm-up fails; requested and effective dates returned | 2020 selection starts first eligible January execution, not 2021 |
| 17 | Wrong short-rank weights | Worst short gets −50%; attribution uses actual signed contribution | Exact rank-weight and leg-P&L tests |
| 18 | Unexplained scoring policy | One versioned Python legacy model and specification parity, explicit unvalidated status; unsupported directional recommendations withheld | Legacy-sign reference tests; empirical efficacy/domain interpretation remain unresolved |
| 19 | No acquisition deadlines/cancellation | Fixed-source bounded loader, timeouts, retry budget, cancellation ownership, byte/observation limits | Timeout, cancellation, transient failure and size-limit tests |
| 20 | Cacheable demo failures / no telemetry | No demo fallback; 503/no-store on failures; structured request IDs/outcomes/durations | HTTP error/cache tests; deployed alert delivery still requires production setup |
| 21 | No behavioral gates | Financial/data/market/API suites, real-browser lifecycle tests and pinned CI | Local suite results recorded below; CI has not yet run remotely |
| 22 | Undeclared moving browser/tooling deps | No browser CDN; Python/npm manifests and locks; declared Playwright, uv setup and CI checks | Locked install, lint, browser suite and dependency audits |
| 23 | Contradictory setup and capabilities | New current README, model/data contracts and operational runbook; V4 prose archived | Route/setup checks and documentation review |

## External completion conditions

- The extended data_mesh producer must supply the required real histories and trustworthy availability/revision metadata. The application side is implemented; the shared producer is outside this repository and was not modified.
- The legacy sector model's economic interpretation and predictive efficacy require domain review and empirical evaluation. Preserving it as explicitly unvalidated research avoids silently inventing a different investment strategy. Directional Risk Bias remains unavailable until a supported model is approved.
- Production routing, approved data entitlements, deployment identity, alert destination and deployed readiness must be verified during rollout. This task does not claim a production release.

## Verification record

- `uv sync --locked` and `npm ci`: passed using the committed lockfiles.
- `npm run check`: Ruff lint, formatting (26 Python files) and browser JavaScript syntax checks passed.
- `uv run pytest -q`: **115 passed**. One upstream Starlette TestClient/httpx deprecation warning remains; no failing tests.
- `npm run test:legacy`: **3 passed**.
- `npm run test:ui`: **9 passed** in Chromium, including repeated runs, request races, failure clearing, immutable parameters, inert provider strings, file-mode guidance and mobile layout.
- A separate browser smoke against the actual Python API with an explicitly synthetic local snapshot rendered all three strategies and four charts without JavaScript/CSP errors; mobile layout stayed inside the viewport. This does not validate a real data feed.
- `uv run pip-audit` and `npm audit --audit-level=moderate`: no known vulnerabilities reported for the resolved dependencies on 2026-10-19.
- `git diff --check`: passed. The annotated rollback tag was verified on origin at the baseline commit.

CI configuration is included but has not run remotely. The implementation branch has not been pushed or deployed.
