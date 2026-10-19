# Market Regime Radar

V5 is a daily market dashboard and reproducible sector-rotation research tool. Python calculates market analytics and portfolio results from versioned snapshots; the browser renders those results. V4's former demo panels now have real calculations within the redesigned UI.

**The current preview uses explicitly labelled mock inputs.** The same calculations and snapshot contract will consume the extended data_mesh feed. Sector coefficients and regime rules are unvalidated research assumptions; signal strength and historical similarity are not calibrated probabilities. Mock performance does not establish an investment edge.

The signal overview prioritizes horizon direction and disagreement, the largest standardized daily move, volatility and sector leadership. Green/coral distinguish direction and preferences; amber marks disagreement or elevated readings; cyan provides context. Ordinary moves remain labelled ordinary, even when they are the day's largest. Charts have selectable series and pointer/keyboard inspection (arrow keys, Home/End). Primary evidence stays visible; complete tables, source identities and methodology remain expandable. Regime and severity classifications use the calculation API's published labels.

## Run locally

Requirements: Python 3.13+, [uv](https://docs.astral.sh/uv/). Node 24+ is needed only for browser tests and the optional legacy Node handlers.

Start the requested synthetic preview (with no real snapshot path/URL configured):

```bash
uv sync --locked
RADAR_DATA_MODE=mock uv run uvicorn app:app --host 127.0.0.1 --port 8000
```

Alternatively, `npm run dev:mock` starts the preview with reload. The generator supplies 62 correlated daily series from June 2018, with seeded shocks and changing regimes. It generates observations, not precomputed dashboard scores. Mock provenance appears on screen and in API responses/downloads. `RADAR_MOCK_SEED` changes the reproducible scenario (default `8042`).

To connect real data, use real mode and configure a published snapshot:

```bash
uv sync --locked
export RADAR_DATASET_PATH=/absolute/path/to/published/radar.json
RADAR_DATA_MODE=real uv run uvicorn app:app --host 127.0.0.1 --port 8000
```

Open **http://127.0.0.1:8000/**. Opening `index.html` directly displays connection guidance; a file URL cannot supply the Python API. `.env.example` documents settings; the application does not automatically load `.env` files. For a remote snapshot, configure `RADAR_DATASET_URL` instead of a local path. Optional `RADAR_DATASET_TOKEN` is a server-side bearer token for that distribution endpoint.

Mock mode refuses an existing real snapshot path/URL rather than masking it. Real mode without a valid source reports unavailable; provider failure never activates synthetic inputs.

## Data and capabilities

The core universe is 16 ETFs: the eleven US sector funds XLB/XLC/XLE/XLF/XLI/XLK/XLP/XLRE/XLU/XLV/XLY, plus SPY/QQQ/GLD/USO/UUP. Supply separate USD quoted closes and consistently defined total-return indices. The nine macro series are DGS2/DGS5/DGS10/DGS30/DFII10/T10YIE/VIXCLS/BAMLH0A0HYM2/DFF. No fundamental or company technology-edge scoring is implemented.

| Capability | Behavior |
|---|---|
| Market observations | Supplied quoted prices, sources, observation dates and per-series freshness |
| Changes, momentum and correlations | Date-aligned return histories; insufficient or incompatible data remains unavailable |
| Risk, changes and anomalies | 1D/1W/1M research scores, divergence, factor contributions, prior-history z-scores and percentiles |
| Rates | Curve snapshots/spreads/decomposition, real yields and inflation compensation, movement-based regimes and duration signals |
| Volatility | Realized 5/10/20/60-session volatility, implied/realized ratios and premium, term structure, VVIX/SKEW/MOVE and explicit regime rules |
| FX and correlations | Eight pairs, FX/cross-asset matrices, USD/risk-currency composites, equity/bond correlation and breaks |
| Sector positioning and playbook | Ranking, additive factor scores, style proxies, conditional preferences, scenario matrix and triggers |
| Historical analogues | Causal feature normalization, nearest nonoverlapping states and subsequent completed outcomes; descriptive, not forecasts |
| Historical backtests | Three strategies, configurable ranked basket, weekly/monthly/quarterly decisions, subsequent execution and complete histories |
| Comparison and rotation | Benchmark statistics, annual returns/excess, daily drawdowns, rolling 12-month excess, holdings, persistence and contribution diagnostics |
| Robustness studies | Nine Top-N/frequency combinations, four cost scenarios, regime-conditioned outcomes and explicit assumptions |

The backtest modes are:

- `extreme1`: +200% highest-ranked sector and −200% lowest-ranked sector.
- `ranked3`: the legacy API name for a configurable ranked basket. Default Top 3 uses +50/+25/+25% and −50/−25/−25% in worst-first order. For `top_n=1`, each side gets 100%; for 2–5, rank 1 gets 50% and the remaining half is shared equally.
- `longonly3`: +100/+65/+45% in the best three, with the extra long notional financed.
- `compare`: all three concrete strategies on exactly the same validated dataset.

Decisions occur at the selected weekly/monthly/quarterly boundary; execution follows at the next exchange-session close. Macro normalization remains based on prior completed months. Evaluation dates are separate from warm-up. Fees cover both signed legs, drift rebalancing, entry and final liquidation. Funding/borrow accrues over elapsed days; insolvency is terminal. See the [financial model](docs/model.md), [analytics formulas](docs/analytics.md), [feature-parity matrix](docs/v4-feature-parity.md) and versioned [specification](engine-spec.json).

## Source and API ownership

```text
shared provider ingestion → data_mesh snapshot → radar/data.py
                                              ├─ radar/market.py
                                              └─ radar/engine.py
                                                        ↓
                                              radar/app.py → browser
```

`app.py` is the FastAPI deployment entry point. `data_mesh` remains a private Python access library; this project defines the snapshot interface its extended producer must publish. The radar does not invent a nonexistent data_mesh HTTP API or fetch paid providers on each request. See [data contract and publisher](docs/data-contract.md).

| Endpoint | Contract |
|---|---|
| `GET /api/market` | Current observations and coverage; HTTP 503 when core data is stale/unavailable |
| `GET /api/analytics` | Ten calculated research sections, dated dataset and model identity |
| `GET /api/backtest` | Required `start=YYYY-MM-DD`; optional `end`, `mode`, `cost_bps`, `short_borrow_bps`, `rebalance`, `top_n` |
| `GET /api/studies` | Same parameters; bounded robustness and cost-sensitivity studies |
| `GET /api/health` | Data readiness, dataset identity and application version |
| `GET /api/model` | The versioned research specification |
| `GET /api/openapi.json` | Machine-readable route and parameter schema |

Costs default to 10 bps per one-way traded notional; annual short borrow defaults to 50 bps. Zero is valid. Invalid/duplicate/unknown parameters return 400 before data acquisition; unsupported methods return 405. `costBps`, `shortBorrowBps` and `topN` are migration aliases. `rebalance` accepts `weekly`, `monthly` (default), `quarterly`; `top_n` is an integer 1–5 and changes only the ranked basket. Responses identify immutable dataset, mock/real source, model, parameters, actual period and strategy identities. Non-finite results cannot be published.

## Check changes

```bash
npm ci
npm run check
npm test
npm run test:legacy
npx playwright install chromium
npm run test:ui
uv run pip-audit
npm audit
```

No live provider/database credentials are needed for tests. `uv.lock` and `package-lock.json` record resolved dependencies. Browser charts use native SVG; no CDN JavaScript executes in the page. CI runs financial, data, HTTP, lint, dependency and real-browser checks.

## Operations and review

- [Runbook, deployment checks, limits and rollback](docs/runbook.md)
- [Finding-by-finding remediation](REMEDIATION.md)
- [Original 23-finding audit](IMPROVEMENTS.md)
- [data_mesh coverage assessment before the revamp](.review-summary/data-mesh-fit.md)
- [Historical V4 release notes](docs/legacy-release-history.md)

Rollback tag: **`pre-revamp-2026-10-19`**, preserved on origin at `6b1e466d2e475addccbb7e7eed69f2a871f938ce`. Current work is on `codex/radar-revamp`. No shared database migration or production deployment is performed by these source changes.
