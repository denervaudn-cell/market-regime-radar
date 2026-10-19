# Review evidence and readiness

Completed 2026-10-19 (Europe/Zurich) against `6b1e466d2e475addccbb7e7eed69f2a871f938ce` on main. Remote: denervaudn-cell/market-regime-radar. The working tree was initially clean; a fetch of the configured upstream confirmed 0 ahead / 0 behind. All source findings refer to that revision.

## Readiness assessment

**Overall: 2/5 — research prototype with material correctness failures.** This is a qualitative readiness score, not a computed quality metric or investment rating. Scale: 1 = unusable foundation; 2 = prototype with unresolved critical behaviors; 3 = key behaviors validated offline; 4 = verified deployment; 5 = observed operational and model-validation evidence.

| Dimension | Assessment |
|---|---|
| Architecture | Small and understandable; duplicate engines/runners and implicit DOM contracts create real drift |
| Data integrity | Fails temporal alignment, freshness, missingness and complete-period publication cases |
| Financial correctness | Demonstrated accounting, timing, strategy-selection and metric defects |
| Testing | No tracked automated suite or CI; review probes reproduce failures but are not a maintained test suite |
| Documentation | Feature history is extensive; current setup/methodology/runtime contract is incomplete and contradictory |
| Security | Server-side credentials and fixed upstreams are positive; resource bounds and safe error rendering need work; no confirmed critical exploit |
| Operations | Platform ceilings/cache intent exist; request budgets, cancellation and application outcome evidence are incomplete |
| Investment evidence | Heuristic strategy with no established holdout, calibrated conviction, or verified implementable financing model |

**23 findings: 11 High and 12 Medium.** No Critical exploit was established. High findings concern material normal-workflow correctness and availability. Medium financial findings remain necessary before treating performance as investment evidence.

## Verification actually performed

Three specialist agents covered code/architecture, documentation, financial testing, security, and performance. The coordinator consolidated findings, checked primary sources, and obtained independent review of the report and business assessment.

| Check | Result / implication |
|---|---|
| Import api/market.js, api/backtest.js, market.js, backtest.js | All four succeed on review host Node 24.5.0 |
| Compile four inline scripts with Node VM | All parse; this does not prove runtime behavior |
| Actual API with mocked historical providers | longonly3 curve equals ranked3; compare response lacks its required nested objects |
| Actual inline scripts with fake DOM/Chart ownership contract | Initial automatic backtest succeeds; first manual rerun encounters an already-owned canvas |
| Risk Bias stress fixture | Computed BEARISH 100%; visible NEUTRAL 50% unchanged |
| Successful Long Only followed by failure | Prior 6.4% fixture CAGR and chart retained beneath error status |
| Non-overlapping market histories | September 2026 SPY and September 2025 QQQ produce correlation 1; old Treasury observations remain LIVE |
| One missing XLC month | Three performance periods disappear; 26 becomes 23 while response remains successful |
| Blank provider values | Blank DFF becomes 0; blank ETF close still produces successful results |
| Short-only turnover changes | Flat-price alternating shorts have the same costs and NAV as unchanged shorts |
| Opening leveraged trades | At 10 bps, +200%/-200% opening trade charges 20 bps; one-way absolute-notional reference would be 40 bps |
| Current partial month | Final observation on April 2 still counts as a completed April period |
| Independent Sharpe oracle | Alternating +20%/-20% returns: correct zero-cash Sharpe 0; implementation approximately -0.3002 |
| Insolvency stress | -60% move at 2x yields NAV -20, then continues; growth metrics serialize null |
| Evaluation start | 2020 selection first reports March 2021 with complete available fixture data |
| Zero input costs | Explicit 0/0 replaced by 10/50 bps |
| Nonfinite and malformed request | Infinity succeeds with null metrics; fractional Top-N in non-extreme mode fails only after fetching; unknown mode succeeds |
| Acquisition fan-out | One historical request: 19 concurrent fetches, zero AbortSignals |
| Early acquisition failure | Response returns while 18 sibling fetches remain active |
| Market provider 429 | HTTP 200 DEMO_FALLBACK with live-style cache policy |
| Dependency/source observations | CDN served Chart.js 4.5.1; anonymous DFF CSV measured 424,315 bytes/26,406 lines |

The fee example assumes a one-way absolute-traded-notional convention; the application must specify that convention. The short-change omission is defective independently of the convention. Insolvency is a constructed stress case, not evidence that actual ETF history reached negative equity. The initial-NAV peak **is** included in the existing max-drawdown metric; no missing-initial-loss finding was retained.

### Diagnostic reproduction artifacts

Temporary scripts and outputs were retained outside the repository during this session:

- `/tmp/market-radar-financial-probes.cjs`
- `/tmp/mrr-ui-audit-6b1e466.mjs`
- `/tmp/mrr-ui-audit-6b1e466-output.txt`
- `/tmp/mrr-market-contract-probe.mjs`
- `/tmp/mrr-market-contract-probe-output.json`
- Specialist notes: `/tmp/market-radar-financial-review.md`, `/tmp/market-radar-frontend-review.md`, `/tmp/market-radar-ops-review.md`

These are diagnostic material, not durable CI artifacts or additional production source. The durable observations are summarized here. No line-coverage percentage was measured; absence of a tracked test suite must not be confused with a measured zero-percent runtime coverage report.

### Limits

No paid Twelve Data requests, live historical strategy run, production load test, real-browser visual test, order execution, source fix, commit, push or deployment was performed. One anonymous FRED payload and the public Chart.js asset were fetched for bounded measurements. Other web reads checked official technical/financial documentation.

Unknowns include actual Vercel project protections, headers, runtime, environment variables, deployment artifact, log destinations, GitHub branch protection, provider entitlements/adjustment behavior, commercial data rights, and real strategy returns. The findings describe source and reproduced behavior; they do not certify deployment exposure or quantify real-world performance distortion.

## Guideline alignment

Baseline: local Cerebrum `03-Technology/GUIDELINES_TECHNICAL.md`, unchanged file with last commit `3a1413a`, 2026-09-18. GitHub canonical retrieval returned 404. The relevant company defaults apply to JavaScript behavior even where examples use Python.

| Guideline area | Current contradiction | Acceptance evidence |
|---|---|---|
| Outcome/publication semantics | Demo/history fixtures beside LIVE, invalid numerical success, silent missing periods | Explicit success/degraded/blocked statuses, visible coverage and no fabricated performance |
| Financial source semantics | Dates dropped, blank becomes0, no source-freshness checks | Date-aware normalized schema; independently tested missingness, units and freshness |
| Point-in-time rules | Month-close information traded at same close | Availability-aware decision/execution fixtures and dated historical inputs |
| Shared calculation ownership | Root/API/browser rules differ; no authoritative deployed engine | One financial owner and version; parity/contract tests; proportional Python alignment for shared production use |
| Versioned scoring/reference cases | Incomplete spec and unvalidated directions/defaults | Formula and domain meaning documented; independently justified normal/boundary/failure examples |
| Testing/CI | No maintained critical-behavior suite | Mapped offline reference tests plus routed preview/browser checks |
| Runtime/resource budgets | 19 fetches without deadlines/coalescing or admission budget | Bound and cancel work; verify actual provider-plan limits and response outcomes |
| Observability | No application boundary outcomes; cacheable fallback | Redacted timed outcome events reaching existing monitoring destinations |
| Release/dependency traceability | New root features not served; moving CDN code | Actual source/runtime/dependency identity tied to tested artifact and rollback |
| Documentation ownership | Key and capability statements conflict | One current setup, route/methodology and operational contract |

The guidelines explicitly require proportional, incremental adoption. This review does not demand a new account system, database, observability platform, universal coverage target, or wholesale React migration. Changes to financial meaning need an explicit domain decision; mechanical repairs to approved rules can proceed normally.

## Remediation with acceptance gates

### Stage 1 — Truthful product surface

Remove or segregate fixture-only investment/performance evidence; scope the LIVE badge; mark each panel's source and observation date. Disable or accurately label modes unsupported by the routed engine. Repair the frozen Risk Bias only alongside a truthful input/model contract.

**Gate:** every visible analytical result has known provenance and valid parameters, or is clearly demo/unavailable. No synthetic history can be mistaken for actual robustness evidence.

### Stage 2 — Canonical financial behavior

Unify the deployed mode dispatcher and independent calculation ownership. Correct parsing, date alignment, complete calendars, timing, turnover, rank weights, statistics, evaluation warm-up and terminal-capital behavior. Document funding/collateral conventions.

**Gate:** independent fixtures establish exact expected outcomes, including short-only trading, missing bars, same-close publication timing, open months, zero costs and insolvency. Invalid inputs cause no provider work.

### Stage 3 — Reliable UI and operation

Use one runner/renderer and explicit run identity. Add real-browser chart rerun/error checks. Reuse provider datasets, apply time/admission budgets and appropriate fallback caching, and verify redacted outcome logging.

**Gate:** success-to-success and success-to-failure reruns cannot mix results. Timeouts/429s are bounded and diagnosable. Preview tests exercise the actual api/ files.

### Stage 4 — Investment validation

Freeze a coherent model version and dated dataset. Test chronological holdouts, parameter/cost/delay sensitivity, rank stability, factor exposures and appropriate benchmarks. Establish forward paper evidence before extending decision responsibility.

**Gate:** business claims match independently reproducible results and their limitations. A working calculator alone is not evidence of a profitable strategy.

## Review artifacts and change scope

The only repository additions from this task are IMPROVEMENTS.md and the four files in .review-summary/. They contain findings and recommendations; no application fixes were made. Stable finding IDs were generated with the deep-review helper, checked for uniqueness, and the helper scratch directory was cleaned after generation. Reports remain uncommitted and unstaged.
