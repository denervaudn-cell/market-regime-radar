# Financial model v5.1

Canonical implementation: `radar/engine.py`. Machine-readable contract: `engine-spec.json`. Tests verify the specification's version, coefficient matrix and rank weights against the implementation. There is one engine for individual and comparison runs.

**Model status: unvalidated legacy research.** This implementation repairs accounting, timing and publication defects; it does not establish an investable edge. Scores are ranking heuristics, not probabilities, measured fundamentals, company technology assessments or recommendations. Economic signs are preserved from the original repository, including counterintuitive cases described below. Domain review and out-of-sample evaluation remain necessary before making investment claims.

## Required history and units

The backtest requires daily USD total-return index histories for SPY and all eleven US sector ETFs: XLB, XLC, XLE, XLF, XLI, XLK, XLP, XLRE, XLU, XLV, XLY. Snapshot keys have suffix `_TR`. All twelve must use the same `total_return_net` or `total_return_gross` dividend convention; the response identifies which. Quoted closes are separate inputs to the market dashboard and are not used as substitutes for return indices.

Required macro inputs are DGS2, DGS10, DFII10, T10YIE, VIXCLS, BAMLH0A0HYM2 and DFF. Rates, breakevens and spreads use native percent units (5 means 5%, not 0.05 or 500). VIX uses index points. Economic zero rates are valid; missing values, missing markers, non-finite numbers and nonpositive prices are errors. Currency conversion is not performed.

Every observation carries an observation date and the availability timestamp of that specific version. A modern historical download cannot be labeled point-in-time by assigning invented old availability dates. The upstream publisher must establish availability provenance and supply initial versions plus revisions where relevant. Current retrospectively adjusted closes alone do not meet this contract.

The snapshot supplies an exchange calendar. Dataset validation independently compares it with XNYS sessions. Every required ETF return-index series must cover every session from the six-month momentum lookback endpoint through the final evaluated close. Omitting a daily holding price blocks the entire run, including if that ETF is not held at the moment. Missing months are never compressed out of the timeline. The fixed eleven-sector universe is unavailable before XLC's 2018-06-19 inception; evaluation also needs the independent warm-up history below.

## Point-in-time decisions and evaluation dates

1. Each signal decision occurs at 23:59:59 America/New_York on a Friday, calendar month-end or calendar quarter-end, according to the selected schedule. Thus a Friday close followed by a weekend month-end can use information actually available through that Sunday cutoff.
2. Monthly macro values select the latest observation date at or before the cutoff, then the latest version available by that cutoff. Values older than ten calendar days are unavailable. Each historical normalization snapshot is frozen at its own historical month-end cutoff, so later revisions do not rewrite the training history.
3. Six-month momentum uses the last exchange-session index observations in the current month and the month six months earlier for monthly/quarterly schedules. Weekly momentum uses the last session at or before the Friday decision and the same calendar date six months earlier (clamped to a valid date), with versions available at the decision cutoff. All ETF histories must also provide a same-day available version for daily valuation, before 23:59:59 New York time.
4. The target portfolio executes at the **next exchange session close**. It cannot earn a price movement from the decision close to its own initial fill. Execution uses that session's total-return-index mark as an idealized close fill.
5. One completed performance cycle runs from this execution close to the following scheduled execution close. Friday/weekly, month-end/monthly and quarter-end/quarterly decisions are regular; holding cycles have their actual calendar-day lengths. An unfinished final cycle is excluded. No complete-cycle return is manufactured from a partial cycle.
6. `start` selects the first scheduled execution on or after the requested date. It does not truncate the normalization or momentum history. A request between scheduled executions therefore starts at the next selected-frequency execution, disclosed in `first_execution`. `end` bounds available execution endpoints, and is clamped to the snapshot's `as_of`; all actual dates remain in the response. Future request dates and dates before 2018-06-19 are invalid.
7. At least twelve consecutive pre-decision macro snapshots are required. The window expands backward to a maximum of sixty only through contiguous complete older snapshots; a missing optional older month stops that expansion. The actual initial window length and warm-up start are disclosed. Missing any of the mandatory twelve or any evaluated decision is an error. Momentum independently requires six calendar months. Insufficient warm-up is an error, never an automatic later starting point. At least one complete evaluation cycle is required; volatility and Sharpe require at least two.

`period` publishes requested dates, warm-up start, first decision, first execution, first complete return, last complete return, completed cycle count, source availability and whether a trailing partial interval was excluded. Comparison uses the same prepared history and decisions for every strategy. A ruined strategy has its own earlier terminal date.

## Preserved legacy scoring

For each macro factor, compute the current value's sample z-score against the preceding 12–60 monthly snapshots strictly before the decision's calendar month. Weekly decisions use current Friday inputs but never train on the future end of that month. Divide by two and clip to [-1, 1]. A genuinely constant normalization window yields a neutral zero state. The five states are real ten-year yield (`rates`), ten-minus-two-year nominal yield (`curve`), ten-year breakeven (`inflation`), VIX (`vol`) and high-yield option-adjusted spread (`credit`).

For a sector with exposure coefficients `(r, i, v, c, q)`:

```text
macro_score = -rates*r*18 + curve*r*12 + inflation*i*14
              -vol*v*10 - credit*c*12
              + q*(rates*0.25 + inflation*0.25)*8
momentum_score = clip(six_month_total_return / 0.20, -1, 1)*22
score = 50 + macro_score + momentum_score
```

The complete coefficient matrix is in `engine-spec.json` and `EXPOSURES` in the canonical implementation. `q`, historically named `value`, is a fixed assumption, not measured valuation data. Scores are unbounded real numbers; they are not forced into 0–100 and must not be displayed as a calibrated percentage. Ties use ascending ETF symbol for reproducibility.

Preserved signs have consequences: with real-yield state +1 and all other states and momentum zero, XLK scores 66 and XLF 37.2. With volatility state +1, XLV scores 43 and XLY 55. These can resemble contrarian assumptions; their economic rationale has not been approved or empirically established. The revamp does not silently reverse them to match prior dashboard prose.

## Strategy identities

| Mode | Signed target notionals / pre-trade NAV | Gross / net |
|---|---|---|
| `extreme1` | +2 best; -2 worst | 4 / 0 |
| `ranked3` | +0.50 / +0.25 / +0.25 best-first; -0.50 / -0.25 / -0.25 worst-first | 2 / 0 |
| `longonly3` | +1.00 / +0.65 / +0.45 best-first | 2.10 / 2.10 |
| `compare` | Run all three concrete modes above | Separate results |

Ranked short conviction is explicitly worst-first: rank11 gets -50%, rank10 -25%, rank9 -25%. Long-only is leveraged 210% exposure, as requested by the original latest strategy definition. The stable API id `ranked3` accepts `top_n` 1–5, default 3. N=1 allocates 100% to the top and -100% to the bottom. For N=2–5, the highest-conviction rank receives 50% and the remaining ranks share the other 50% equally on each leg; worst short ranks come first. Long and short baskets never overlap in the eleven-sector universe. Extreme and leveraged long-only exposures remain fixed regardless of `top_n`. All modes accept weekly, monthly and quarterly schedules, and comparison applies the same selected schedule to each mode.

## Portfolio accounting

NAV starts at 100 before entry fees. At each execution, signed target notionals equal target weights times **pre-trade NAV**. Existing signed positions have already drifted with daily total returns. Traded notional is the sum, over the union of old and new names, of `abs(target_notional - current_notional)`. Turnover is this notional divided by pre-trade NAV; one-way fees are `traded_notional * cost_bps / 10000`.

Both legs, rank changes, position exits and drift rebalancing incur costs. Opening +200/-200 from cash trades 400% of NAV, hence costs 40bps at a 10bps one-way fee. Since target weights reference NAV before fees, realized exposure relative to NAV immediately after fees is slightly higher. No circular post-fee sizing approximation is used.

A cash ledger pays for trades and fees; signed position values evolve daily with the supplied total-return index ratios. Negative signed positions therefore pay the dividend component implicit in total return. DFF funding is charged on extra long notional above equity, established at each rebalance and fixed until the next one: `max(initial_long_notional - pre_trade_NAV, 0)`. The model does not finance long exposure using reusable short proceeds. Short proceeds are treated as segregated collateral with no interest rebate. Unused cash earns no return in strategy NAV.

Each close-to-close interval charges:

```text
funding = debt_at_last_rebalance * available_annual_DFF * actual_calendar_days / 365
short_borrow = prior_close_short_notional * annual_borrow_rate * actual_calendar_days / 365
```

The DFF value must be available by the actual XNYS close timestamp on the interval's initial session (including early closes); unreleased same-day observations cannot fund that interval. The last known eligible rate remains fixed across weekends and exchange holidays. Borrow uses the prior close's marked short notional, so it changes as short positions drift. DFF and borrow assumptions are transparent research costs, not a prime broker margin or financing quote. The exchange calendar determines the rate cutoff on early-close sessions as well as ordinary sessions.

Entry costs and final liquidation costs are included. The final trade closes all positions at the final eligible execution mark; liquidation notional, turnover and costs are separately recorded in the final holdings row. The SPY total-return benchmark is frictionless and covers exactly the same execution dates. No extra benchmark leverage, trading fee or borrowing fee is applied.

Costs in a holdings row are fractions of that cycle's starting NAV. Diagnostic cost sums are sums of these period-relative fractions, **not** cumulative dollar costs or a geometrically compounded drag estimate. `long_contribution` and `short_contribution` are signed contributions to portfolio return, so profitable short positions have positive contribution. They are not unlevered asset returns and are never divided by two indiscriminately.

## Insolvency and numerical outcomes

NAV is checked after entry fees and each daily close, plus final liquidation. NAV at or below zero terminates that strategy immediately. Published NAV is capped at zero, terminal date is returned, no subsequent position is opened and later market recovery cannot revive the portfolio. This is a terminal-loss convention; deficit liabilities, recapitalization and bankruptcy recovery are not modeled. Intraday margin calls, borrow recalls, locate availability, close auction participation and market impact are outside this simulation.

A terminal partial cycle is retained as an explicitly incomplete holdings row and a terminal zero equity observation. It is excluded from completed-period statistics. CAGR, Sharpe, volatility and hit rate are unavailable after insolvency with `terminal_insolvency` reasons, rather than reporting a plausible metric from an economically undefined continuation. Total return and terminal drawdown are -100%. Non-finite arithmetic produces a typed data error rather than JSON null disguised as successful calculation.

## Statistics

- **Total return:** final NAV / initial NAV - 1, including entry, all intervening costs and final liquidation.
- **CAGR:** `(final_NAV / initial_NAV) ** (365.25 / elapsed_calendar_days) - 1`. Insufficient/terminal numerical cases are explicitly unavailable. Calendar duration is never inferred from a count of retained rows.
- **Annualized volatility:** sample standard deviation of completed cycle net returns times sqrt(52), sqrt(12) or sqrt(4) for weekly, monthly or quarterly cycles respectively.
- **Sharpe:** arithmetic mean of cycle excess returns divided by their sample standard deviation, times sqrt(52), sqrt(12) or sqrt(4) for weekly, monthly or quarterly cycles respectively. Cash reference is the interval-compounded available DFF ACT/365 return over each identical holding cycle. Reference cash is for the metric; the trading strategy's collateral still earns no rebate. Zero excess-return variance gives null with a reason.
- **Daily drawdown:** minimum daily marked NAV / running daily peak - 1, including entry, rebalance and final liquidation costs and terminal insolvency. `max_drawdown` and `max_drawdown_daily` use this full path. The compatibility field `max_drawdown_monthly` is recomputed from the last daily mark in each calendar month, including partial boundary-month endpoints. Neither measure models intraday margin survival.
- **Hit rate:** proportion of completed cycles whose net strategy return exceeds matching SPY total return. This is not a probability of future outperformance.
- **Annualized turnover:** sum of one-way trade turnovers, including entry and exit, divided by actual elapsed years. Each trade turnover uses that trade's pre-trade NAV.

Volatility and Sharpe use the selected schedule's conventional 52/12/4 cycle scaling even though actual calendar lengths differ. Short samples can produce unstable annualized estimates. Every null metric has a machine-readable reason. The historical exposure and financing assumptions need domain review and out-of-sample validation; tests establish implementation behavior, not market efficacy.

## Independent acceptance examples

`tests/test_engine.py` uses synthetic histories clearly confined to tests and actual exchange sessions. Hand-derived cases cover: opening 400% gross costs 40bps at10bps; unchanged longs with a changed 200% short trade400%; rank-weight swaps; drift from +200/-200 to +220/-200 with NAV120 trades60 on rebalance; a pre-fill price jump earns nothing; later macro revisions cannot rewrite a prior decision; missing daily dates and whole calendar months block; 32 calendar days accrue32/365 funding; alternating +20/-20 returns have zero zero-cash Sharpe despite negative CAGR; and a 60% long-asset fall at2x terminates the portfolio before a later recovery.


## Calendar-year, benchmark and rotation research

Each result includes complete SPY benchmark statistics over precisely the strategy's actual evaluation dates: total return, elapsed-time CAGR, frequency-scaled volatility and cash-excess Sharpe, daily and calendar-month drawdown, positive-period rate and zero turnover. The strategy hit rate is *outperformance of SPY*; the benchmark hit rate is *positive SPY periods*. The API includes `hit_rate_basis` so these are not confused. A strategy that terminates early also truncates its benchmark valuation to that date; completed-cycle volatility still excludes an incomplete terminal cycle.

`annual_returns` is calculated from actual daily marked NAV, not by assigning whole monthly cycles to their end year. Each calendar year compounds from the last mark in the preceding year; the first observed year starts from initial pre-fee NAV100. Initial and unfinished final years have `partial: true`. The excess column is the arithmetic difference between the two same-year total returns. Multi-year periods do not infer calendar annual returns from CAGR.

`rolling_excess` is trailing calendar-year strategy total return minus SPY total return, using the last available exchange session at or before the calendar-year lookback date (Feb29 maps to Feb28). No value is published before a full trailing year exists. It is an arithmetic excess return, not a relative-wealth ratio. `drawdown_curve` is derived from daily marks. Daily and rolling charts publish at most400 points using equal time-order buckets that preserve each series' local minima and maxima plus the first/last points; all numerical statistics and annual returns still use every daily mark. The response discloses chart sampling. Equity curves remain one point per completed cycle plus a terminal insolvency point.

Rotation diagnostics use executed positions and contemporaneous rankings:

- `rank_persistence`: mean Spearman correlation of successive full eleven-sector ranks. The model's deterministic alphabetical tie-break applies; this measures its ranking output, not evidence of predictive skill.
- `top_retention`: fraction of the previous long basket retained on the next rebalance, averaged across transitions.
- `average_holding_days`: mean calendar duration of a continuous signed-position spell. A long-to-short change ends one spell and begins another; a weight change that keeps the same side does not. Entry/exit boundaries censor observed spells, so this is observed duration rather than an unbiased survival estimate.
- `average_top_return`, `average_bottom_return` and `average_top_bottom_spread`: arithmetic mean top-sector, bottom-sector and top-minus-bottom total returns across complete cycles. These are unlevered returns before strategy fees; the response identifies `ranking_return_frequency` as weekly/monthly/quarterly, and incomplete terminal cycles are excluded.
- `top_beats_bottom_rate`: proportion of complete cycles in which the highest-scoring sector's unlevered total return exceeded the lowest-scoring sector's return, on actual execution dates.
- `positive_net_spread_rate`: proportion of complete market-neutral strategy cycles with positive net returns after all modeled costs. It is unavailable for the long-only strategy because that strategy does not implement a long/short spread.

Realized sector attribution accumulates actual signed dollar PnL divided by initial NAV100. Sector contributions minus actual trading/funding/borrow costs reconcile final net return; an explicitly reported insolvency-cap residual accounts for clipping negative equity to zero. These are contributions to return, not unlevered security returns. Separate `score_attribution` averages the contribution of each model term to the long and short baskets' scores, normalized to unit gross per leg and excluding the base50. Those values are *score points*, never causal realized-return attribution. The underlying coefficient assumptions remain unvalidated.

## Bounded robustness, cost sensitivity and regime studies

`radar/studies.py` prepares the same immutable history once per schedule and evaluates a fixed nine-cell grid: ranked Top1/3/5 with weekly/monthly/quarterly schedules. Each cell reports its own actual first/last execution dates; schedules can have different completed periods. Unavailable short-period variants remain explicit error rows, never substituted results. The selected-frequency run must itself be valid. Four further scenarios apply one-way costs0/10/25/50bps with all funding and borrow assumptions unchanged. Cost sensitivity uses the selected strategy, or the selected ranked basket when `mode=compare`. It does not optimize a winner or claim that in-sample parameter search validates the model.

Regime-conditioned hit rates assign each complete cycle using only its decision-time normalized inputs. Precedence is: **stress** if volatility or credit state>=0.5; otherwise **inflation** if inflation state>=0.5; otherwise **low_stress** if both volatility and credit states<0; otherwise **balanced**. These transparent research categories are not calibrated predictions. Each group reports sample count, proportion of net returns exceeding SPY, arithmetic average net return and average excess return. Small sample counts remain visible, and partial/terminal cycles are excluded.

The expanded tests independently check frequency timing and annualization, Top-N disjoint weights, calendar-year boundaries, daily drawdown troughs, annual rolling excess, future-month exclusion, attribution reconciliation, signed-position durations, regime thresholds, true cost drag, bounded chart extrema and unavailable grid cells. They establish implementation behavior on synthetic observations, not market efficacy.
