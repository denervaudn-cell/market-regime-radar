# Repository analysis and improvements

> **Historical baseline audit.** Implementation progress and verification for the V5 revamp are tracked in [REMEDIATION.md](REMEDIATION.md). Findings below describe the tagged V4 source, not the rewritten application.

> Completed source review: 2026-10-19 (Europe/Zurich).
> Repository: market-regime-radar · Branch: main · Commit: `6b1e466d2e475addccbb7e7eed69f2a871f938ce`.
> Baseline: local Cerebrum `GUIDELINES_TECHNICAL.md`, last file commit `3a1413a` (2026-09-18).
> Scope: all nine tracked files, specialist source review, current primary documentation, and offline behavioral probes.

## Assessment

**The current dashboard and backtests are not dependable enough to support investment decisions or performance claims.** The main problems are incorrect strategy selection, synthetic evidence presented alongside live data, temporal data errors, and incomplete financial accounting. These are demonstrable implementation defects; the strategy's economic edge remains unproven.

There are **23 actionable findings: 0 Critical, 11 High, 12 Medium, 0 Low**. High means material correctness or availability impact in an intended workflow; it does not mean a confirmed exploitable security vulnerability. No critical exploit or hardcoded application secret was established.

The small static frontend and two serverless functions can be improved incrementally. Credentials remain server-side, the backtest requests adjusted prices, and its provider failure path does not fabricate an equity curve. Those are useful foundations. Fixing known behavior, establishing one engine, and adding independent reference tests takes precedence over a frontend rewrite.

The review used the current clean checkout, fetched only its configured upstream, and confirmed zero divergence. The canonical guidelines GitHub request returned 404, so the unchanged local copy was used. No AGENTS.md, CLAUDE.md, REJECTED.md, or prior IMPROVEMENTS.md was found in the reviewed repository. No prior rejected findings needed filtering.

## Reading guide

- [Architecture and actual capability inventory](.review-summary/overview.md)
- [Business fit, investment assumptions, and validation design](.review-summary/business-context.md)
- [Dependency and security assessment](.review-summary/dependencies.md)
- [Verification evidence, guideline mapping, and remediation sequence](.review-summary/health.md)
- [Contributor archive comparison: V4.27 additions and missing implementation](.review-summary/contributor-archive.md)
- [Market-data requirements and data_mesh fit, including read-only database coverage checks](.review-summary/data-mesh-fit.md)

All behavior reproductions use synthetic data and actual source functions/scripts. UI probes use a lightweight DOM and Chart ownership stub; they are not browser visual tests. No paid Twelve Data calls or deployment mutations were made. Actual production configuration, data entitlements, and provider correctness remain unverified. Application code was not changed.

Effort: S = focused change; M = multiple components/reference cases; L = substantial integration or research. Estimates exclude unresolved domain decisions and are not delivery commitments.

## Critical

None established within the reviewed scope.

## High

### 1. Serve one strategy engine with explicit mode contracts <!-- id:41383921 -->

- **Category**: Code Quality
- **Location**: `api/backtest.js:102,170–200,237–252; backtest.js:163–219; index.html:1885,1917–1925; vercel.json:6`
- **Issue**: The routed API does not implement longonly3 or compare. It treats non-extreme modes as ranked portfolios, while newer implementations exist only in the unreferenced root file. Ranked3 also exposes long-only stats under a Top3/Bottom3 label.
- **Evidence**: Mocked actual handler: longonly3's equity curve equals ranked3's byte-for-byte and the response returns short holdings. Compare lacks longshort/longonly keys. UI labels the former 210% long and fails while reading the latter.
- **Impact**: A successful result describes a different investment strategy from the one selected.
- **Fix**: Use one authoritative engine behind api/backtest.js; validate an exhaustive mode enum and return strategy identity, weights, exposures, and a tested response schema. Bind labels to that identity. Check possible local consumers before retiring duplicate entry points.
- **Guideline**: Interface and Contract Design; Financial Logic and Shared State; Release Verification
- **Effort**: M

### 2. Separate fixture analytics from live market evidence <!-- id:dce7b539 -->

- **Category**: Code Quality
- **Location**: `index.html:82,112–164,250,650–669,1076–1078,1250–1251,1653–1706`
- **Issue**: The global LIVE badge reflects only the market endpoint. Eleven of fifteen views remain fixture-backed. Rotation History claims real-data-only behavior while using demoHoldings, invented alpha/drawdowns, robustness, and cost-sensitivity results; returned historical holdings are unused.
- **Evidence**: Source-to-render inventory confirms the live updater changes the Live Data panel and invokes a broken bias renderer, leaving the other analytical panels static.
- **Impact**: Current recommendations and historical validation can be mistaken for real investment evidence.
- **Fix**: Scope feed status to its panel; show source, observation date, and DEMO/UNAVAILABLE per panel. Remove or clearly segregate fabricated performance. Populate holdings and robustness only from actual calculated results.
- **Guideline**: Outcome and Publication Semantics; Financial Source Semantics
- **Effort**: S for honest presentation; L for full live functionality

### 3. Connect the visible Risk Bias to its calculation <!-- id:cb0203bb -->

- **Category**: Code Quality
- **Location**: `index.html:673–675,1151–1154,1174–1181`
- **Issue**: Markup contains riskBiasTag/riskBiasConviction, while the renderer targets nonexistent multi-horizon IDs and then returns on a missing riskBiasFactors element.
- **Evidence**: Actual scripts in the offline DOM harness compute BEARISH at 100% for a stress fixture, while the visible conclusion remains NEUTRAL at 50%.
- **Impact**: The displayed risk conclusion never changes, even after a successful live refresh.
- **Fix**: Choose and implement one supported visible horizon contract, assert required DOM bindings, and test bullish/bearish display transitions. Validate latent placeholder inputs before enabling the model as live output.
- **Guideline**: Interface Contracts; Critical-Behavior Testing; Publication Semantics
- **Effort**: S

### 4. Align market returns by date and enforce source freshness <!-- id:7009a900 -->

- **Category**: Code Quality
- **Location**: `api/market.js:33–37,59–67,94–97; market.js duplicates this code`
- **Issue**: Correlation pairs independent last-20 return arrays by position, without joining common dates. Summaries and Treasury output discard observation dates; mode becomes LIVE whenever fetching succeeds.
- **Evidence**: Actual handler with SPY prices dated September 2026, identical QQQ prices dated September 2025, and Treasury observations dated 2024-01-01 returns HTTP 200 LIVE, a fresh generatedAt, and correlation 1 despite no overlapping dates.
- **Impact**: Apparently live cross-asset relationships and rates can be temporally invalid or stale.
- **Fix**: Join returns on common start/end observation intervals, enforce a minimum sample/coverage contract, preserve per-series asOf and fetchedAt, and apply explicit stale/missing publication rules. A response timestamp is not data freshness.
- **Guideline**: Financial Dates, Calendars and Freshness; Outcome Semantics
- **Effort**: M

### 5. Respect information availability before historical execution <!-- id:0453c743 -->

- **Category**: Code Quality
- **Location**: `api/backtest.js:43–64,134–147,155–177; backtest.js:114–141,158–168`
- **Issue**: Signals use month-end closing prices and month-dated macro observations, then earn returns from that same close. Observation dates become month keys; publication timestamps and historical vintages are not retained.
- **Evidence**: The Federal Reserve publishes H.15 at 4:15 p.m.; these closing-rate observations are not available before that day's equity close. Today's FRED CSV is not a historical availability ledger. See [H.15](https://www.federalreserve.gov/releases/h15/) and [FRED vintage semantics](https://fred.stlouisfed.org/docs/api/fred/realtime_period.html).
- **Impact**: The claimed point-in-time simulation lacks an executable information cutoff and may use unavailable information.
- **Fix**: Preserve observation/availability dates, choose a documented decision cutoff and subsequent eligible execution price, and test release days and holidays. Use vintages where needed. Revision-bias magnitude was not measured; DFF funding timing alone is not the ranking-lookahead proof.
- **Guideline**: Financial Point-in-Time Semantics; Versioned Scoring Specifications
- **Effort**: M–L

### 6. Do not silently remove missing periods from performance <!-- id:8b10deb1 -->

- **Category**: Code Quality
- **Location**: `api/backtest.js:66–75,128–140,154,167; backtest.js:61–69,108–139`
- **Issue**: Missing required prices or macro/lookback inputs cause entire periods to be skipped. Statistics then annualize retained observations as if they were consecutive months.
- **Evidence**: Removing one XLC month removes three performance rows through return/lookback dependencies. Response remains 200 ok:true, drops from 26 to 23 periods, and retains the same displayed start/end.
- **Impact**: Holding-period P&L and elapsed time disappear, biasing return and risk estimates.
- **Fix**: Validate required calendar coverage before simulation and block with named gaps under the existing real-data-only contract. Any permitted cash/degraded treatment must preserve the complete timeline and have an explicit financial policy.
- **Guideline**: Outcome and Publication Semantics; Financial Missingness and Calendars
- **Effort**: M

### 7. Charge turnover on both signed portfolio legs <!-- id:b8c5081c -->

- **Category**: Code Quality
- **Location**: `api/backtest.js:178–185; backtest.js:155–168`
- **Issue**: Turnover is based only on overlap of long names. It ignores short changes, rank-weight changes, and drift rebalancing, then applies that incomplete measure to costs.
- **Evidence**: With flat assets, fixed longs and alternating shorts, the actual root engine produces identical NAV and turnover to a never-changing short portfolio. At 10 bps, opening +200%/-200% costs 20 bps rather than 40 bps under a one-way absolute-notional fee convention.
- **Impact**: Net performance overstates returns when ignored trades occur; the cost-sensitivity control is unreliable.
- **Fix**: Track signed target and pre-trade drifted weights; charge absolute traded notional on both sides. Specify one-way/round-trip fees and entry/final-liquidation conventions. The exact scaling needs that convention, but free short changes are a definite defect.
- **Guideline**: Financial Units and Calculation Boundaries; Independently Justified Reference Cases
- **Effort**: M

### 8. Preserve missing provider values instead of converting them to zero <!-- id:0de8f702 -->

- **Category**: Code Quality
- **Location**: `api/backtest.js:27,40,52–53; backtest.js:27,41,48–50`
- **Issue**: Number('') converts empty provider values to zero before validation. Empty prices also become zero; nullable return arithmetic can subsequently coerce missing values to zero.
- **Evidence**: Blank DFF becomes v:0. A blank XLB close still yields 200 ok:true with all 26 periods retained in the fixture.
- **Impact**: Absent rates, spreads, or prices can silently alter signals and financial returns.
- **Fix**: Validate raw missing markers before conversion; distinguish legitimate economic zero from missing values; require finite, positive ETF prices and documented rate bounds. Reject invalid required inputs before arithmetic.
- **Guideline**: Financial Representation and Source Semantics; Explicit Unavailable Outcomes
- **Effort**: S–M

### 9. Validate backtest parameters before any provider work <!-- id:d33b72c7 -->

- **Category**: Code Quality
- **Location**: `api/backtest.js:95–116,237–252; backtest.js:190–198`
- **Issue**: Truthy defaults replace valid zero costs, Infinity is accepted, Top-N is not integral, modes are not allowlisted, and malformed or repeated date parameters are coerced.
- **Evidence**: Zero costs/borrow become 10/50 bps. Infinity returns ok:true with null serialized financial values. topN=2.5 with a non-extreme mode causes Invalid array length only after 19 fetches; an unknown mode succeeds.
- **Impact**: Published results can violate the requested assumptions or contain invalid analytics while claiming success.
- **Fix**: Use a single scalar, finite, range-aware parser; preserve zero, reject invalid enums/calendar dates/integer Top-N, return stable 400 errors before fetching, and validate the result contract before publication.
- **Guideline**: Interface and Contract Design; Financial Non-finite Rejection; Resource Budgets
- **Effort**: S

### 10. Give backtest charts and rendering one lifecycle owner <!-- id:340a9295 -->

- **Category**: Code Quality
- **Location**: `index.html:1510,1571–1583,1650,1793–1837,1856–1869`
- **Issue**: The original window-load runner owns lexical chart instances; the later cloned-button runner only destroys different window-owned instances before reusing the same canvases. It also leaves other diagnostics on the previous render path.
- **Evidence**: Actual inline scripts with a Chart ownership stub succeed on initial load, then fail on the first manual Run because the canvas is already owned. New KPIs can be written before the chart failure. [Chart.js requires destruction before canvas reuse](https://www.chartjs.org/docs/latest/developers/api.html).
- **Impact**: A normal rerun fails and can mix new metrics with old charts.
- **Fix**: Consolidate startup/manual execution into one runner and complete renderer with one chart registry or actual-owner lookup. Test success followed by success and failure. The probe is a DOM/Chart stub integration check, not a real-browser rendering test.
- **Guideline**: Runtime Resource Ownership; Code Quality; Runtime Integration Tests
- **Effort**: S–M

### 11. Bound repeated provider consumption and reuse historical datasets <!-- id:d6097a66 -->

- **Category**: Performance
- **Location**: `api/backtest.js:88–116; api/market.js:84–91; index.html:1783–1785,1885–1887,1917–1918`
- **Issue**: Each backtest launches 12 Twelve Data and seven FRED requests, without dataset reuse, in-flight coalescing, or an application admission budget. no-store and timestamp cache-busting repeat all acquisition. POST also executes the workload.
- **Evidence**: Mocked GET and POST each trigger 19 fetches at peak concurrency 19. Twelve Data documents per-symbol credits; actual account limits and Vercel access controls were not inspected. [Credit accounting](https://support.twelvedata.com/en/articles/5615854-credits).
- **Impact**: Ordinary reruns waste quota; exposure to unrestricted traffic would amplify outages and compute/provider consumption.
- **Fix**: Reject unsupported methods; reuse dated provider datasets across parameter changes, coalesce loads, and apply provider-plan-aware admission/concurrency controls using existing platform facilities. Bound requested history while retaining warm-up. Do not invent a login requirement for a public information site.
- **Guideline**: Execution Budgets; Provider Limits; Performance and Resource Efficiency
- **Effort**: M

## Medium

### 12. Associate every displayed result with immutable run parameters <!-- id:69a8862a -->

- **Category**: Code Quality
- **Location**: `index.html:1846–1849,1882–1898,1912–1964`
- **Issue**: Failure handlers retain previous KPIs/charts/holdings while changing a status line. Controls remain editable during fetches; results have no request identity or stale-parameter guard.
- **Evidence**: A successful Long Only fixture followed by provider failure retains its prior 6.4% CAGR and chart under DATA UNAVAILABLE. Parameter-race exposure is established by source review, not a browser concurrency test.
- **Impact**: Old or mixed results may appear under a newly selected period or cost assumption.
- **Fix**: Keep one run-state object with immutable parameters and source/result identity. Clear invalid output or visibly retain it as a previous run. Disable controls or reject out-of-date completions, and render all result components atomically.
- **Guideline**: Derived-value Freshness; Outcome and Interface Semantics
- **Effort**: S–M

### 13. Separate incomplete months from completed-period statistics <!-- id:99322c7c -->

- **Category**: Code Quality
- **Location**: `api/backtest.js:58–75,125–129,183–184; backtest.js:54–64,106–109,160`
- **Issue**: The final available observation of a month is treated as a complete monthly endpoint, with full-month annualization, funding, and borrow assumptions.
- **Evidence**: Changing the final observation to April 2 still publishes April as one of the same 26 completed periods.
- **Impact**: Current-month returns and accrued costs distort comparisons with completed monthly periods.
- **Fix**: Retain exact endpoint dates; exclude an open month from completed-month statistics or explicitly publish MTD with proper elapsed-time accrual. Align the endpoint across required series.
- **Guideline**: Financial Calendars, Units and Freshness
- **Effort**: S–M

### 14. Calculate Sharpe from period excess returns <!-- id:0c6efcf5 -->

- **Category**: Code Quality
- **Location**: `api/backtest.js:68–75; backtest.js:63–69`
- **Issue**: The field called Sharpe equals CAGR divided by volatility, with no declared cash/reference-return treatment.
- **Evidence**: Six alternating +20%/-20% pairs have zero mean return and zero Sharpe against zero cash, but the implementation reports -0.3002 because CAGR is negative. [Sharpe's definition](https://web.stanford.edu/~wfsharpe/art/sr/sr.htm).
- **Impact**: The named risk-adjusted performance metric can misrank strategies.
- **Fix**: Use arithmetic mean period excess return divided by sample deviation of those excess returns with the documented annualization convention; keep CAGR separate. Zero variance requires a typed unavailable result. Completed monthly returns legitimately use monthly scaling.
- **Guideline**: Versioned Financial Formula and Reference Cases
- **Effort**: S

### 15. Define terminal portfolio behavior after insolvency <!-- id:90d38a25 -->

- **Category**: Code Quality
- **Location**: `api/backtest.js:68–75,187–216; backtest.js:63–69,163–175`
- **Issue**: Leveraged returns continue compounding after NAV reaches or passes zero; no terminal ruin, margin, or recapitalization state exists.
- **Evidence**: A stress fixture with a -60% long move at 2x reaches NAV -20, then trades for 12 more rows and produces -120% drawdown with null serialized CAGR/Sharpe.
- **Impact**: The simulator can present an economically undefined continuation as an ordinary strategy path.
- **Fix**: Specify financing/margin and terminal-loss semantics; stop or explicitly model authorized recapitalization and emit safe metric statuses. Label monthly drawdown as monthly: daily/intramonth margin survival is not tested by month-end points.
- **Guideline**: Financial Invariants; Unavailable Metrics; Versioned Model Boundaries
- **Effort**: M; includes domain specification

### 16. Separate requested evaluation start from model warm-up <!-- id:06899203 -->

- **Category**: Code Quality
- **Location**: `api/backtest.js:95–96,109,125,128; backtest.js:190–198,106–108; index.html:358,384`
- **Issue**: The requested start also truncates training/lookback data, followed by a 13-month loop offset.
- **Evidence**: With complete fixture data, selecting 2020 begins reported returns in March 2021, excluding the entire COVID crash from that selection.
- **Impact**: A period selector does not cover the period a user reasonably expects.
- **Fix**: Fetch pre-start normalization/momentum history separately, then apply the evaluation cutoff. Report requested start, warm-up, first trade, and first return; disclose genuine universe-inception constraints.
- **Guideline**: Financial Calendar Semantics; Consumer Contracts
- **Effort**: S–M

### 17. Map short conviction weights to the worst ranks explicitly <!-- id:e06d0c1a -->

- **Category**: Code Quality
- **Location**: `api/backtest.js:168–174,227–231; index.html:481; engine-spec.json:145–181`
- **Issue**: The bottom slice remains in descending score order, so weights 50/25/25 go to ranks 9/10/11 rather than 11/10/9. Ranked diagnostics also divide returns by two unconditionally.
- **Evidence**: The documented strongest short conviction receives only 25%, while the least extreme selected short receives 50%.
- **Impact**: The ranked short portfolio and its diagnostics do not express the stated strategy.
- **Fix**: Define signed rank-to-weight mappings per supported mode and test asymmetric sector returns. Scope diagnostic leverage normalization to the strategy actually calculated.
- **Guideline**: Versioned Financial Rules and Reference Cases
- **Effort**: S

### 18. Make the score specification explain and constrain the model <!-- id:1f466e1c -->

- **Category**: Code Quality
- **Location**: `api/backtest.js:9–20,155–165; index.html:1126–1145,1208–1236,1320–1327; engine-spec.json:139–229`
- **Issue**: The specification is unconsumed, omits the actual exposure/formula matrix, and contains conflicting fallback/version claims. Some score directions contradict dashboard prose. Latent live-bias code hardcodes volatility/credit stress and calls curve slope a rate shock.
- **Evidence**: At other states/momentum zero, high real-rate state gives XLK 66 versus XLF 37.2; high volatility gives XLV 43 versus XLY 55. These could be intended contrarian rules, but no such rationale/reference cases exist. The frozen renderer means latent bias values are not currently visible.
- **Impact**: Fixing display wiring alone can promote an unexplained heuristic into apparently live financial advice.
- **Fix**: Document intended formula/signs/weights, units, missingness and horizon definitions; independently justify reference cases and empirical evaluation. Label conviction as heuristic unless calibrated. Resolve meaning with the domain owner rather than mechanically flipping coefficients. Plan canonical Python ownership before shared production integration.
- **Guideline**: Canonical Financial Ownership; Versioned Scoring and Reference Cases; Proportionate Adoption
- **Effort**: M–L; domain decisions required

### 19. Bound provider time and cancel failed acquisition work <!-- id:f82883a5 -->

- **Category**: Performance
- **Location**: `api/backtest.js:29–55,109–117; api/market.js:42–57,90–91; vercel.json:3–7`
- **Issue**: Fetches have no application deadline or abort signal; Promise.all failure does not cancel siblings. No bounded transient/429 recovery policy exists.
- **Evidence**: The first mocked fetch failure returns a server error with 18 sibling fetches still active and no aborts. Platform ceilings are 30/60 seconds, not graceful provider time budgets.
- **Impact**: Slow or rate-limited providers can consume the entire execution window and encourage repeated failed runs.
- **Fix**: Set an end-to-end deadline below platform limits, provider timeouts, bounded concurrency and sibling cancellation. Retry replay-safe GETs only within a capped transient-error policy with backoff, jitter, and applicable Retry-After.
- **Guideline**: Replay-safe Retries; Runtime Ownership; Execution Budgets
- **Effort**: M

### 20. Give degraded feed responses distinct caching and telemetry <!-- id:4f18c7b7 -->

- **Category**: Code Quality
- **Location**: `api/market.js:85,88,98–99; api/backtest.js:254–255`
- **Issue**: Market failures return HTTP 200 DEMO_FALLBACK with the same s-maxage=900/stale-while-revalidate=3600 policy as live results. Neither endpoint emits application boundary outcomes or timed provider diagnostics.
- **Evidence**: A mocked provider 429 produces cacheable demo success. Machine mode labeling exists, but success-status-only monitoring cannot distinguish the failure.
- **Impact**: Recovered data can remain hidden behind cached fallback and operators lack application-level failure context.
- **Fix**: Use explicit degraded/failure outcome and short/no-cache fallback policy, with source coverage/asOf. Emit redacted request IDs, outcomes, provider statuses and durations; verify logs/alerts reach existing operational destinations. Deployment monitoring outside the repo remains unknown.
- **Guideline**: Error Handling; Logging and Observability; Outcome Semantics
- **Effort**: S–M

### 21. Add critical-behavior tests for the deployable artifact <!-- id:ca644aa1 -->

- **Category**: Testing
- **Location**: `package.json:5–9; repository-wide absence of tests and CI configuration`
- **Issue**: No tracked test suite, test command, critical-behavior mapping, or CI workflow protects the financial engine or UI/API contracts.
- **Evidence**: All four JS modules import and all four inline scripts parse, yet multiple financial and UI defects reproduce under small offline fixtures. Syntax checks do not establish correctness.
- **Impact**: A change in the wrong duplicate file or a plausible but wrong financial result can reach release undetected.
- **Fix**: Retain behavior-based cases for modes, costs, availability, missing dates/values, statistics, insolvency and repeated UI runs. Add one real-browser smoke check for chart lifecycle and a routed preview contract check; tie relevant checks to release. No universal coverage percentage or framework rewrite is required.
- **Guideline**: Testing and CI; Release Verification; Independent Financial Reference Cases
- **Effort**: M for initial gates

### 22. Record and test the browser and development dependencies actually used <!-- id:7d0c8927 -->

- **Category**: Code Quality
- **Location**: `index.html:7; package.json:5–9`
- **Issue**: Chart.js loads from a moving unversioned CDN URL outside the manifest, while the dev command relies on an undeclared Vercel CLI. Exact release dependency/runtime evidence is absent.
- **Evidence**: The CDN served Chart.js 4.5.1 and 208,522 bytes during review; source does not promise that version. No applicable CVE-2020-7746 exposure was found for that version. Deployed Node version is unknown.
- **Impact**: Executable browser code can change without a repository commit, and fresh setup depends on external global tooling.
- **Fix**: Declare/document tooling and package or record an exact integrity-checked browser artifact; test and record actual deployed versions while actively adopting updates. Refresh the supported runtime declaration without assuming production runs Node 20 merely because engines says >=20.
- **Guideline**: Dependency Management; Release Artifact Traceability
- **Effort**: S–M

### 23. Document the current product and endpoint setup unambiguously <!-- id:d26a15ff -->

- **Category**: Documentation
- **Location**: `README.md:13–16,201–224; api/market.js:87–88; engine-spec.json:139–229`
- **Issue**: The append-only release history contradicts current endpoint requirements and capabilities. V4.22 says no FRED key is needed, but the live market endpoint still requires it. No authoritative setup, route map, verification command or failure runbook exists.
- **Evidence**: Following the newest key guidance leaves market data in demo mode. README comparison/shared-load claims describe root code rather than the routed API.
- **Impact**: Deployments can be misconfigured and maintenance can again target a file that is not served.
- **Fix**: Lead README with actual setup, per-endpoint keys, capability/source matrix, supported parameters, quotas/freshness and release checks. Preserve history separately, remove contradictory current claims, and name the authoritative calculation/route owner.
- **Guideline**: Documentation Ownership; Interface Contracts; Release Traceability
- **Effort**: S

## Low

No additional standalone findings; scoped hardening observations are in the dependency report.

## Summary

| Category | Critical | High | Medium | Low | Total |
|---|---:|---:|---:|---:|---:|
| Security | 0 | 0 | 0 | 0 | 0 |
| Code Quality | 0 | 10 | 9 | 0 | 19 |
| Performance | 0 | 1 | 1 | 0 | 2 |
| Testing | 0 | 0 | 1 | 0 | 1 |
| Documentation | 0 | 0 | 1 | 0 | 1 |
| **Total** | **0** | **11** | **12** | **0** | **23** |

Security-specific observations are scoped in the dependency report; absence of a confirmed exploit is not a production security certification. Most findings concern financial data integrity and application behavior.

## Recommended order

1. Make the product truthful: isolate synthetic panels, expose unavailable/stale states, and remove misleading strategy labels.
2. Establish the deployed engine and contracts; repair date alignment, parsing, financial accounting, and timing with independent fixtures.
3. Consolidate UI ownership and result state; add routed API and real-browser smoke checks.
4. Bound provider acquisition and make failure states observable; verify the actual deployed artifact and existing platform controls.
5. Validate the investment hypotheses out of sample with explicit financing, risk, and benchmark conventions before expanding their business role.

Detailed acceptance gates are in [health.md](.review-summary/health.md). No source fixes, commit, push, or deployment were performed as part of this analysis.
