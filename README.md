# Market Regime Radar V4 — live-data ready

## V4
- `/api/market` Vercel serverless endpoint
- Twelve Data daily market series (SPY, QQQ, XLF, XLK, XLE, GLD, USO, UUP)
- FRED US Treasury series (DGS2, DGS5, DGS10, DGS30)
- automatic 1D / 20D changes
- daily-return z-score and empirical percentile
- rolling 20-day correlation matrix
- live Treasury curve
- automatic DEMO fallback if API keys are missing or a provider fails

## Vercel environment variables
Add:
- `TWELVE_DATA_API_KEY`
- `FRED_API_KEY`

Do not put API keys in index.html.

## Next
Add Cboe volatility ingestion (VIX/VIX9D/VIX3M/VVIX) and credit series, then feed the live values into Anomaly Engine / What Changed Today.


## V4.1
- Today's Market Narrative ajoute un **Risk Bias** explicite: BULLISH / NEUTRAL / BEARISH
- conviction en %
- principaux facteurs expliquant le biais

## V4.2
- Risk Bias devient dynamique
- BULLISH / NEUTRAL / BEARISH calculé automatiquement
- conviction en % calculée à partir de l'amplitude du score
- pondération multi-facteurs : momentum actions, choc taux, stress de corrélation, volatilité, crédit et USD
- le bloc Today’s Market Narrative se met à jour avec les données de `/api/market`

## V4.3
- Risk Bias multi-horizon
- 1 DAY / 1 WEEK / 1 MONTH
- chaque horizon affiche BULLISH / NEUTRAL / BEARISH + conviction
- détection des divergences entre court terme et régime de fond
- message d'alignement si les 3 horizons pointent dans la même direction

## V4.4
- Regime Divergence Alert
- LOW / MID / HIGH divergence classification
- highlights conflicts between 1D, 1W and 1M risk bias
- identifies possible transition regimes instead of treating every short-term shock as structural

## V4.5 — Volatility Regime Dashboard
- implied vs realized volatility
- realized vol 5D / 10D / 20D / 60D
- volatility risk premium (IV - RV)
- IV/RV ratio and historical percentile
- short-term realized-vol acceleration
- term structure diagnostics
- VVIX, SKEW, MOVE/VIX
- volatility regime classification: LOW/CHEAP, NORMAL, RICH, STRESS, PANIC
- automatic volatility narrative and vol bias

## V4.6 — Rates Regime Dashboard
- richer Treasury curve analytics
- 2s10s / 5s30s / 2s30s / 10s30s
- level / slope / curvature decomposition
- nominal vs real yield decomposition
- 5Y / 10Y breakevens and 5Y5Y inflation
- MOVE integration
- rates regime map
- BULL/BEAR STEEPENER and FLATTENER classification
- duration bias and confidence
- automatic rates narrative

## V4.7 — Sector Allocation Engine
- translates macro/rates/volatility regime into equity-sector preferences
- sector score 0-100
- OVERWEIGHT / NEUTRAL / UNDERWEIGHT classification
- factor contribution by rates, inflation, volatility, credit and momentum
- style rotation view: Value / Quality / Low Vol / Growth / High Beta / Bond Proxies
- automated sector narrative and portfolio translation

## V4.8 — Sector Allocation Backtest
- Top-N sector long-only backtest
- Top-N long / Bottom-N short strategy
- benchmark comparison
- CAGR / Sharpe / max drawdown / hit rate / turnover
- annual excess return
- performance attribution
- robustness checklist
- current values are illustrative until full historical point-in-time data are connected

## V4.9 — Real Historical Backtest Engine
- removes illustrative backtest numbers from the UI
- `/api/backtest` downloads sector ETF histories and macro series
- point-in-time monthly scoring
- signals formed at month-end t, returns earned from t to t+1
- Top 3 long-only and Top 3 minus Bottom 3
- transaction costs included
- real CAGR / volatility / Sharpe / drawdown / hit rate / turnover
- FRED macro series: DGS2, DGS10, DFII10, T10YIE, VIXCLS, BAMLH0A0HYM2
- requires `TWELVE_DATA_API_KEY`

## V4.9.1 — Backtest visibility fix
- backtest tab now always renders
- embedded browser fallback if `/api/backtest` is unavailable
- clear DEMO FALLBACK label until the real API is connected
- Run backtest button added
- real calculations replace fallback automatically when the API succeeds

## V4.10 — Rotation History & Robustness
- historical Top 3 / Bottom 3 sector holdings
- regime shown for each rebalance
- rolling 12M excess return
- strategy vs benchmark drawdowns
- Top-N / rebalance-frequency robustness matrix
- transaction-cost sensitivity
- regime-conditioned hit rates
- real API endpoint now returns recent holdings history too

## V4.11 — Regime Playbook
- converts macro regime into sector/style actions
- current playbook: favor / neutral / avoid
- regime matrix across rates, volatility and credit combinations
- conviction score
- scenario triggers that invalidate or change the playbook
- signal hierarchy / factor weights
- actionable conclusion and guardrails

## V4.12 — FX Regime Dashboard
- FX correlation matrix
- EURUSD / USDJPY / USDCHF / GBPUSD / AUDUSD / USDCAD / USDCNH / AUDJPY
- FX vs SPX / Gold / Copper / Oil / real yields
- Dollar Regime Score
- Risk FX Score
- FX regime narrative
- FX contribution integrated into Regime Playbook

## V4.13 — Conviction-Weighted Backtest
- Top 1 sector = 50%
- Top 2 sector = 25%
- Top 3 sector = 25%
- same weighting on the short side
- long gross exposure = 100%
- short gross exposure = 100%
- net exposure = 0%
- gross exposure = 200%

## V4.14 — Extreme Conviction Backtest
- selectable mode: +200% best-ranked sector / -200% worst-ranked sector
- net exposure = 0%
- gross exposure = 400%
- keeps the 50/25/25 Top3 vs Bottom3 mode for comparison

## V4.15 — Extreme Best vs Worst is now the default
- primary backtest = +200% long sector ranked #1
- primary short = -200% sector ranked last
- net exposure = 0%
- gross exposure = 400%
- Top3/Bottom3 mode kept only as a comparison option

## V4.16 — Backtest controls fix
- Run backtest now reads Start / Rebalance / Top-N / Costs / Mode from the UI
- cache-busting added so repeated runs actually refresh
- button shows Running… while the request is executing
- status line shows the selected parameters
- live engine currently supports monthly rebalance; weekly/quarterly now return a clear message instead of silently doing nothing

## V4.17 — Top 1 / Bottom 1 explicit
- backtest UI now explicitly shows Top 1 Long and Bottom 1 Short
- Top 1 = +200%
- Bottom 1 = -200%
- latest ranked sectors displayed directly in KPI cards
- net exposure = 0%, gross exposure = 400%

## V4.18 — Extreme Ranking Diagnostics
- live ranking stability
- average Top 1 / Bottom 1 holding duration
- average best-vs-worst spread
- Top 1 beats Bottom 1 hit rate
- positive spread after costs
- long-side vs short-side contribution

## V4.19 — Backtest truly interactive
All selectors now recalculate charts and KPIs. Weekly/monthly/quarterly work locally; monthly can upgrade to live API data.

## V4.20 — Real S&P 500 benchmark direction
- local fallback no longer invents the S&P 500 annual direction
- historical annual S&P 500 returns anchor the benchmark
- 2021 is positive (+28.7% total return)
- 2022 is negative (-18.1% total return)
- live API remains the preferred source for the exact daily/monthly path

## V4.21 — Real-data-only backtest
- simulated performance removed
- no fallback equity curve
- requires TWELVE_DATA_API_KEY + FRED_API_KEY
- sector and SPY prices requested with `adjust=all` (splits + dividends)
- full 11-sector universe constrained to XLC inception: 2018-06-19
- real funding cost uses FRED Effective Federal Funds Rate (DFF)
- short borrow cost is explicit and user-selectable
- if any required series is unavailable, UI displays Data unavailable

## V4.22 — FRED key removed
- only `TWELVE_DATA_API_KEY` is required
- FRED macro and funding series load from public CSV endpoints
- no `FRED_API_KEY` needed
- real-data-only backtest policy remains unchanged
