# Restored V4 market research

`radar.analytics.market_analytics` computes every displayed market research panel from the immutable snapshot. It does not contact a provider or substitute illustrative panel values. Explicit mock mode changes the input observations, not these calculations. The response identifies `1.0.0-research-unvalidated` and the separate sector engine version.

The new rules below fill gaps where V4 used static demonstrations or undefined calculations. They are documented research conventions, not empirically validated forecasting models. Scores and signal strength are never labelled probabilities. A real data_mesh feed will populate the same contract; investment validation remains separate.

## Response and observation conventions

The response includes `ok`, `status`, `dataset_id`, `as_of`, `model_version`, `sector_model_version`, `sections`, `inputs`, `input_issues` and `assumptions`. The API attaches snapshot `source` provenance. Ten section keys are always present: `risk`, `changes`, `anomalies`, `correlations`, `rates`, `volatility`, `fx`, `sectors`, `playbook` and `analogues`.

Each section exposes a status, title, narrative summary, metric objects `{label,value,unit}`, tables `{title,columns,rows}` and charts `{title,unit,series:[{label,points:[{date,value}]}]}`. Table columns are strings and rows are arrays. Numeric missingness is JSON null. Percent values use percentage points: `5` means 5%, not 500%. Chart `date` is an ISO day for histories and a categorical label for maturities or forward-session offsets. Metrics may contain descriptive strings.

The current publication cutoff is 16:30 America/New_York. Each historical session uses only observation versions released by its own 23:59:59 New York cutoff, capped by the supplied `now`. Late revisions never rewrite past states. An economic date is retained until that date arrives even when its UTC publication timestamp falls on the prior New York date. A later revision of an older date cannot replace a newer economic date.

ETF histories require USD net or gross total-return indices with one consistent dividend convention; quoted prices never enter return analytics. FX uses exact session observations and explicit quote orientation. Macro/index levels permit at most three calendar days of lag and expose their source observation dates. Rate spreads/decompositions and combined volatility measures require matching economic dates. All daily return intervals require both consecutive exchange-session endpoints; multi-session returns require complete intermediate coverage. Missing inputs, insufficient history or a constant denominator produce partial/unavailable results. A stale snapshot is labelled stale throughout and never reports `ok: true`.

## Risk, changes and anomalies

Risk is computed independently for 1, 5 and 20 exchange sessions (1D/1W/1M). Each horizon's change is standardized against the preceding 252 observations of that same horizon, excluding the endpoint; at least 60 valid observations are required. For factor change `x`, the bounded signal is `clip(z(x)/3, -1, +1)`.

| Factor | Sign | Weight |
|---|---:|---:|
| SPY total-return momentum | Positive | 35% |
| 10Y yield change | Negative | 15% |
| VIX change | Negative | 20% |
| High-yield credit spread change | Negative | 15% |
| UUP total-return momentum | Negative | 10% |
| Positive 20-session SPY/TLT correlation | Negative | 5% |

The final factor contributes `-5 × max(correlation, 0)`; the others contribute `100 × weight × sign × signal`. The total lies in −100…+100. Scores above +20 are Bullish, below −20 Bearish and otherwise Neutral. Strength is absolute score magnitude. Divergence is the maximum minus minimum of the three scores: LOW below 35, MID from 35 to below 80, HIGH from 80. Direction agreement is separately identified, so low numerical divergence can still accompany differing labels. Every factor contribution and 252-session score history is inspectable.

Daily changes are total returns for assets/FX, basis-point changes for rates/credit and index-point changes for volatility indices. Acceleration is today's change minus the prior session's change, including a five-session history. The anomaly z-score uses the preceding 252 daily changes, minimum 60. The percentile uses `(number below + 0.5 × number equal) / count`; ties therefore receive their midpoint rank. Absolute z ≥2 is ELEVATED and ≥3 is HIGH. Ranking uses absolute z, while the signed z and observed move remain visible. Flat reference variance yields zero only if the endpoint equals the historical mean; otherwise normalization is unavailable.

## Correlations

SPY, QQQ, XLF, XLK, XLE, GLD, USO, UUP, TLT and CPER use ordinary Pearson correlation of daily total returns over 20 and 60 sessions. Pairwise joins use the same session endpoints; at least 75% of the selected window must remain (15 or 45 samples). Constant series produce null, including their diagonal.

The equity/bond relationship is SPY versus TLT. A correlation break is `abs(corr20 − corr60) ≥ 0.35`. Both correlations and their difference have 252-session histories. These describe rolling relationships, not structural causation or statistical break-test significance.

## Rates

Treasury curves show 2Y/5Y/10Y/30Y observations today and 1, 20 and 60 sessions earlier. Four slope spreads—10Y−2Y, 30Y−5Y, 30Y−2Y and 30Y−10Y—also have 252-session histories.

- Level: average of the four nominal yields.
- Slope: 10Y−2Y.
- Curvature: `2×5Y−2Y−10Y` (an explicit butterfly convention, not a fitted principal component).
- Decomposition residual: nominal 10Y−real 10Y−supplied 10Y breakeven.
- Percentiles: current level, slope, curvature, real yield and inflation measures against their prior 252 sessions, excluding today.

The rate regime uses 20-session changes in level and slope. Falling level is BULL, rising level BEAR; rising slope is STEEPENER, falling slope FLATTENER. An absolute movement below 5bp in either component produces STABLE / MIXED. Duration bias follows the level move, with a ±5bp neutral band. Strength is `min(100, abs(level change)/0.50 ×100)`, a movement scale rather than confidence. MOVE is an independently supplied observation.

5Y and 10Y breakevens and 5Y5Y forward inflation are supplied series, not reconstructed from a mismatched curve. FRED describes [5Y breakeven inflation](https://fred.stlouisfed.org/series/T5YIE) as the nominal-versus-inflation-indexed yield difference. Its [5Y5Y forward series](https://fred.stlouisfed.org/series/T5YIFR) compounds the 5Y and 10Y breakeven terms; the simple `2×10Y−5Y` expression is not its exact formula. Mock inputs use the compounded relationship.

## Volatility

Realized volatility is `100 × sample_std(log(Pt/Pt−1)) × sqrt(252)` for 5, 10, 20 and 60 complete sessions of SPY total-return data. IV is the supplied VIX value, already expressed as annualized volatility percent. [Cboe explains](https://www.cboe.com/insights/posts/what-the-vix-and-vix-1-d-indices-attempt-to-measure-and-how-they-differ/) that VIX targets 30-day expected volatility and that VIX9D, VIX3M, VIX6M and VIX1Y cover other horizons.

The dashboard calculates IV−RV20 in volatility points, IV/RV20, the ratio's prior-252-session percentile, RV5−RV20 acceleration, VIX9D/VIX3M, term slope `VIX3M−VIX`, and curvature `2×VIX3M−VIX−VIX6M`. All combined current observations must share dates. The premium has a 252-session history. VVIX, SKEW and MOVE are supplied index observations; MOVE/VIX is a descriptive ratio of different indices, not a conversion into equal units of risk.

Classification is ordered: PANIC if VIX ≥40; otherwise STRESS if VIX ≥30 or VIX9D/VIX3M ≥1.10; otherwise RICH if IV/RV20 ≥1.5; otherwise LOW/CHEAP if VIX <15 or IV/RV20 <1; otherwise NORMAL. Missing critical inputs yield unavailable classification. These thresholds are transparent research rules. IV−RV is not an option-return forecast, and a rich reading is not an instruction to sell volatility.

## FX

The eight pairs are EURUSD (USD/EUR), USDJPY (JPY/USD), USDCHF (CHF/USD), GBPUSD (USD/GBP), AUDUSD (USD/AUD), USDCAD (CAD/USD), USDCNH (CNH/USD) and AUDJPY (JPY/AUD). The table shows quotes, 1D/20D returns and 20/60-session FX correlation matrices. Cross-asset correlations use 60 sessions against SPY, GLD, CPER, USO and daily DFII10 changes; yield levels are never correlated with currency returns.

The dollar score averages seven bounded standardized 20-session signals, signing EURUSD/GBPUSD/AUDUSD negative and the four USD-base pairs positive. The risk FX score averages positive AUDUSD and AUDJPY with negative USDCNH. Each pair is normalized against its own preceding 252 sessions (minimum 60), divided by three and clipped before scaling to ±100. Weights are equal, not DXY weights. All component inputs are required; a missing currency does not silently renormalize the basket. Histories show 120 sessions. USD >20 with risk FX <−20 is a tightening/risk-off combination; otherwise risk FX >20 is supported, USD <−20 weakening, and the remaining states mixed.

## Sector allocation and playbook

Current rankings call the same `score_sectors` and `sector_score_components` functions as the backtest. No duplicated coefficient formula exists. Macro state uses up to 60 contiguous prior calendar-month snapshots (minimum twelve), frozen at their own month-end cutoffs; the engine's ten-calendar-day macro limit applies to those monthly snapshots. Current state uses the latest eligible daily inputs. Each state is the clipped half-z against the monthly baseline. A zero-variance baseline follows the engine convention of state zero. Momentum runs from the last session of the calendar month six months earlier to the current session, requiring complete total-return histories for all eleven sectors.

Raw scores determine ranking and remain unbounded; a separately labelled display score clips to 0–100. The top three are OVERWEIGHT, bottom three UNDERWEIGHT, remainder NEUTRAL. Factor contributions sum exactly from a base of 50 to the raw score. The legacy coefficients remain unvalidated, including their economic signs; the restoration does not quietly recalibrate them.

Style views average the raw scores of explicit sector proxies: Value (XLF/XLE/XLB), Quality (XLV/XLP), Low volatility (XLU/XLP/XLV), Growth (XLK/XLC/XLY), High beta (XLY/XLI/XLB), and Bond proxies (XLU/XLRE). Mean ≥55 is Favor, ≤45 Avoid, otherwise Neutral. These overlap and are not measured fundamentals, technology-edge ratings or investable factor benchmarks.

The playbook preserves the sector ranking and displays independent risk/FX confirmation. VIX ≥30 or normalized credit >0.75 activates a defensive review guardrail; risk score <−20 or risk FX <−20 flags a headwind. Dollar >20 is a tightening trigger. Ranking-separation strength is `min(100, 2×(best score−worst score))`. Eight conditional scenarios recompute the actual sector model with rates/volatility/credit states at ±1, current curve/inflation retained and momentum neutral. The matrix, preference buckets, trigger states and signal hierarchy are all visible; no order execution or hidden score adjustment occurs.

## Historical analogues

The six features are SPY 20-session momentum, VIX, high-yield spread, 2s10s slope, 10Y real yield and UUP 20-session momentum. Each endpoint is standardized independently against only its own preceding 252 observations, minimum 60, then clipped to ±5 standard deviations. The current state never changes a candidate's historical normalization.

Candidates exclude the most recent 20 sessions and require all features. Rank by root-mean-square feature distance; ties use the earlier date. Select up to eight greedily, requiring more than 20 sessions between endpoints so their forward windows do not overlap. Similarity is `100/(1+distance)`, a display transform rather than a calibrated likelihood. The feature table compares current and nearest historical normalized states.

Only after selection are subsequent 20-session SPY, GLD and TLT total returns calculated. Missing or incomplete outcomes remain null and do not affect ranking. Forward SPY paths, outcome dates, complete sample count, mean, median and the observed positive-outcome fraction are visible. Those small-sample outcomes describe historical selected episodes; they are not a validated conditional forecast. The present-state selection is not presented as a backtested predictive model.

## Required extension and checks

The core 41-series contract is extended by TLT/TLT_TR, CPER/CPER_TR, T5YIE, T5YIFR, VIX9D, VIX3M, VIX6M, VIX1Y, VVIX, SKEW, MOVE and the eight FX pairs above: 62 series total including displayed quotes. Macro rates use `price_basis=rate, unit=percent`; volatility indices use `index/index`; FX uses `price_basis=fx` and the exact orientation units listed above. A partial real feed stays partial.

`tests/test_analytics.py` covers independent realized-volatility arithmetic, basis-point spreads, same-date joins, risk contribution sums, percentile ties, total-return versus quoted-price separation, exact-interval correlations, missing/constant histories, FX orientation, engine score parity, future releases and revisions, timezone boundaries, causal analogue features, nonoverlapping outcomes and chart-to-metric consistency. The current full mock calculation completes in a few seconds within the API work budget; the API owns caching and request limits.
