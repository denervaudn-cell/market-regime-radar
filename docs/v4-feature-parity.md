# V4 feature restoration in the V5 interface

Scope: all V4 feature families from `pre-revamp-2026-10-19` and its release history, including previously hardcoded panels. The new interface remains in place. Source values are currently explicit synthetic inputs; all output values below are calculated by Python. No old demo result tables are used.

| V4 feature | Implementation and visible result |
|---|---|
| Market snapshot | Quoted closes, dividend-inclusive 1D/20-session changes, daily z-score/percentile, source dates and refresh |
| Multi-horizon risk | 1D/1W/1M signed scores, direction, strength, divergence, factor contributions and history |
| Daily changes / anomalies | Prior-history normalized changes, acceleration, ranked magnitudes, percentiles and dynamic explanatory text |
| Correlations | 20/60-session cross-asset matrices, equity/bond history and correlation-break diagnostics |
| Rates | Today/prior/1M/3M curve, 2s10s/5s30s/2s30s/10s30s, level/slope/curvature, nominal/real/breakeven/forward inflation, MOVE, regime and duration signals |
| Volatility | Realized 5/10/20/60-session volatility, IV/RV and premium, percentiles/acceleration, term structure, VVIX/SKEW/MOVE ratios and regime interpretation |
| FX | Eight pairs, FX and cross-asset correlations, USD and risk-FX composites, history and playbook input |
| Sector allocation | All eleven current ranks, raw and bounded display scores, overweight/neutral/underweight research labels, additive factor contributions and style proxies |
| Playbook | Favor/neutral/avoid sets, rates/vol/credit scenario matrix, rule triggers, factor hierarchy, guardrails and dynamic stance |
| Historical matches | Causally normalized states, nonoverlapping nearest matches, distance/similarity and subsequent completed 20-session outcomes |
| Strategies | Extreme +200/−200%, ranked basket, leveraged long-only 100/65/45%; comparison includes all three and SPY |
| Controls | Start/end, weekly/monthly/quarterly schedules, Top-N 1–5 for ranked basket, one-way costs and annual short borrow |
| Performance | Full strategy and SPY statistics, annual returns/excess with partial-year labels, daily marked drawdowns and rolling 12-month excess |
| Rotation history | Actual dated holdings/weights, decision scores and macro states, persistence, holding duration and latest selected sectors |
| Ranking diagnostics | Best-vs-worst spread, top-beats-bottom frequency, net positive spread, long/short contributions and retention |
| Attribution | Realized signed sector contributions and reconciled costs; factor score contributions are separately labelled score points |
| Robustness | Nine Top-N/frequency variants, four cost scenarios, per-scenario periods/status and regime-conditioned outcomes |
| Provenance and exports | Immutable dataset/model/parameter identities, source kind/seed, JSON exports and stale-request protection |

## Deliberate semantic corrections

- Confidence percentages from old demos are replaced with explicitly defined signal strength or similarity, not asserted forecast probabilities.
- Sector/style preferences are research model outputs. Style baskets use declared sector proxies, not company fundamentals or estimated technology edge.
- Fixed extreme/long-only strategy exposures do not change when Top-N changes; only the ranked basket changes. The API keeps the legacy `ranked3` identifier for compatibility.
- Weekly and quarterly strategies still normalize macro factors against prior complete months, preserving a causal monthly training basis.
- Chart sampling may reduce plotted points on long histories; exact statistics use every daily marked NAV. Sampling metadata accompanies the result.
- Missing real inputs remain unavailable. The explicitly selected mock mode is not an automatic fallback.

See [model conventions](model.md), [analytical formulas](analytics.md) and [data contract](data-contract.md). Empirical predictive validation and real data_mesh producer integration are separate from functional parity and mock-based verification.

## Verification

Final integrated verification is recorded in [REMEDIATION.md](../REMEDIATION.md). Calculation tests cover independent numerical identities and data-timing edge cases; HTTP/browser tests exercise actual computed responses as well as lifecycle failures. A mock preview validates software behavior, not historical investment performance.
