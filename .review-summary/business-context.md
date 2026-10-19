# Business and investment assessment

Review date: 2026-10-19 (Europe/Zurich). Source revision: `6b1e466d2e475addccbb7e7eed69f2a871f938ce`.

## Assessment

The repository combines three distinct products: a market monitoring dashboard, a rule-based sector ranking model, and a historical portfolio simulator. Each needs its own evidence. A plausible macroeconomic explanation does not establish predictive power; predictive power does not establish an investable portfolio after financing, turnover, and risk constraints.

The current implementation is a research prototype. Verified defects in data presentation, deployed strategy selection, costs, and historical calculations prevent treating its outputs as validated investment evidence. This conclusion concerns implementation and validation readiness; it is not a finding that sector rotation can never work.

## Fit with Apollo 8

Apollo's local Cerebrum mission describes data analysis supporting capital allocation. The Invest Agent overview describes equity scoring, portfolio construction, and discretionary mandates. A reliable regime radar could support analysts and investment committees by explaining changes in market conditions and testing allocation hypotheses.

No integration from this repository to Invest Agent, custody, client holdings, order management, or execution was established. Its US sector ETF universe is a research universe; it does not establish suitability for every Apollo mandate, access through a particular custodian, or an approved portfolio overlay.

Potential users and useful outcomes:

| User | Useful decision support | Evidence required |
|---|---|---|
| Investment analyst | Identify changes in rates, volatility, credit, and sector behavior | Actual observations, freshness, units, and explainable calculations |
| Portfolio manager / committee | Compare sector hypotheses and identify concentrated exposures | Stable rankings, out-of-sample tests, costs, and risk decomposition |
| Engineer / operator | Deliver reproducible calculations and diagnose missing inputs | One deployed engine, versioned inputs, tests, and explicit failure outcomes |

These are proposed roles inferred from the product, not a verified deployment or user roster.

## Economic hypotheses to test

1. **Rates:** rate changes can affect discount rates, financing costs, and sector earnings differently. The cause of a move matters: improving growth and an inflation shock can produce the same nominal-yield direction with different equity implications.
2. **Curve and real yields:** curve shape, real yields, and inflation compensation can add context, but correlated inputs can double-count the same macro move.
3. **Volatility and credit:** stress indicators may identify changing risk conditions; that does not automatically identify the best future sector or a profitable short.
4. **Momentum:** relative momentum offers an explicit ranking hypothesis. It should be compared with a momentum-only baseline to establish whether the macro overlay adds value.
5. **Extreme rankings:** selecting only the highest and lowest scores magnifies ranking noise. Adjacent scores need not imply economically distinct expected returns.

Fixed weights and thresholds are research assumptions until tested. A displayed conviction percentage should be described as a heuristic score unless a defined outcome and calibration exercise establish a probability interpretation. Repairing the frozen Risk Bias display alone would not validate its underlying model.

## Portfolio interpretation

The advertised extreme strategy holds +200% in one sector and -200% in another. Its net notional is zero and gross notional is 400%. Zero net notional does not imply zero market beta, balanced factor exposures, limited drawdown, or a self-financing implementation without collateral constraints.

The advertised Long Only strategy allocates 100% / 65% / 45%, totaling 210%. Comparing its raw return with unlevered SPY combines selection, leverage, and financing effects. The deployed API currently does not implement this advertised mode correctly; conclusions from that screen are premature.

Before presenting either strategy as investable, specify rebalancing and execution timing, mark-to-market frequency, financing balance, treatment of short-sale proceeds and collateral, borrow assumptions, distributions, margin limits, and the response to insolvency. The purpose is a coherent economic model, not merely more controls in the UI.

SPY is useful as a familiar USD total-return reference. Add an equal-weight sector baseline and a momentum-only baseline for selection research. Evaluate the leveraged long-only strategy against an explicitly financed exposure-matched baseline. Evaluate long/short results against its declared cash/collateral convention and report market and sector-factor exposures. These comparisons separate exposure from selection; they are proposed research designs, not investment recommendations.

## Validation sequence

1. Establish exact, independently checked accounting on small fixtures before assessing historical returns.
2. Freeze a versioned research specification: inputs, availability cutoffs, universe, weights, thresholds, costs, units, and missing-data policy.
3. Reconstruct historical decisions using only information available before the chosen execution time. Store dataset/version and actual usable date range.
4. Separate model development from evaluation. Use chronological holdouts or walk-forward evaluation; document parameter searches and avoid treating a reused test set as fresh evidence.
5. Run sensitivity tests around weights, thresholds, turnover costs, borrow, execution delay, and rebalance frequency. Unsupported frequencies must not appear as functioning controls.
6. Test crises and non-crisis periods, rank stability, return attribution, beta/factor exposures, and capacity assumptions. Monthly endpoints cannot establish intramonth margin survival.
7. Observe a forward paper portfolio with frozen rules and dated predictions before extending the model's role in capital allocation.

The 11-sector universe is constrained by XLC's 2018 inception and the macro-normalization and momentum warm-up requirements. It cannot demonstrate full-universe behavior in 2008 or earlier. Extending history requires an explicit universe/reconstruction design, not an invented pre-inception price series.

This validation approach follows the distinction between backtesting, historical stress tests, simulation, and sensitivity analysis described in [CFA Institute's backtesting overview](https://www.cfainstitute.org/insights/professional-learning/refresher-readings/2026/backtesting-and-simulation).

## Practical priorities

First make data status truthful and make the UI select the strategy actually calculated. Then correct the financial engine and retain the regression cases. After that, establish empirical evidence and a bounded operating model. Add new panels or finer narrative only once those foundations hold.

A wholesale frontend rewrite is not a prerequisite. Consolidating the duplicate engines and runners, creating explicit contracts, and testing the existing behavior provides a focused path. Apollo's canonical guidelines assign shared financial semantics to Python; plan that ownership before this model becomes a shared production component, without allowing a language migration to delay correction of known defects.

## Sources and limits

- Local Cerebrum: `01-Company/About/Mission-Statement.md`; `01-Company/About/Business-Description-FR.md`; `02-Products/Invest-Agent/README.md` (business context, not proof this repository is integrated).
- Local Cerebrum: `03-Technology/GUIDELINES_TECHNICAL.md`, last file commit `3a1413a`, 2026-09-18. The canonical GitHub API read returned 404; local contents were used.
- Repository README, specialist source review, and mocked execution evidence summarized in [health.md](health.md) and [IMPROVEMENTS.md](../IMPROVEMENTS.md).
- [FRED real-time periods](https://fred.stlouisfed.org/docs/api/fred/realtime_period.html) distinguishes information available today from historical vintages. The magnitude of revision bias in this particular strategy was not measured.
- No claim is made about achieved alpha, actual production performance, custodian financing terms, licensing, mandate approval, or client suitability.
