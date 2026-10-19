# Market Regime Radar

V5 is a daily market dashboard and reproducible sector-rotation research tool. A single Python engine consumes versioned snapshots from Apollo's data distribution. The static frontend contains no financial scoring logic and no invented market or backtest values.

**The extended data_mesh feed is an external prerequisite.** Without a configured, validated snapshot, the application starts and clearly reports data unavailable. It does not fall back to a demo. The legacy sector scoring rules remain explicitly unvalidated research assumptions; the old directional risk-bias score is withheld pending model review.

## Run locally

Requirements: Python 3.13+, [uv](https://docs.astral.sh/uv/). Node 24+ is needed only for browser tests and the optional legacy Node handlers.

```bash
uv sync --locked
export RADAR_DATASET_PATH=/absolute/path/to/published/radar.json
uv run uvicorn app:app --host 127.0.0.1 --port 8000
```

Open **http://127.0.0.1:8000/**. Opening `index.html` directly displays connection guidance; a file URL cannot supply the Python API. `.env.example` documents settings; the application does not automatically load `.env` files. For a remote snapshot, configure `RADAR_DATASET_URL` instead of a local path. Optional `RADAR_DATASET_TOKEN` is a server-side bearer token for that distribution endpoint.

## Data and capabilities

The core universe is 16 ETFs: the eleven US sector funds XLB/XLC/XLE/XLF/XLI/XLK/XLP/XLRE/XLU/XLV/XLY, plus SPY/QQQ/GLD/USO/UUP. Supply separate USD quoted closes and consistently defined total-return indices. The nine macro series are DGS2/DGS5/DGS10/DGS30/DFII10/T10YIE/VIXCLS/BAMLH0A0HYM2/DFF. No fundamental or company technology-edge scoring is implemented.

| Capability | Behavior |
|---|---|
| Market observations | Actual quoted prices, sources, observation dates and per-series freshness |
| Changes, momentum and correlations | Date-aligned return histories; insufficient or incompatible data remains unavailable |
| Treasury, volatility and FX views | Show only supplied or validly derived observations; optional coverage is explicit |
| Historical backtests | Three explicit strategies, shared dataset, dated availability, delayed execution and complete daily histories |
| Comparison and holdings | Actual returned curves, signed weights, costs and period outcomes |
| Directional Risk Bias | Unavailable pending model review; actual underlying observations remain visible |
| Historical analogues, robustness and recommendations | No fabricated output or claims; unsupported analytics are clearly unavailable |

The backtest modes are:

- `extreme1`: +200% highest-ranked sector and −200% lowest-ranked sector.
- `ranked3`: +50/+25/+25% in the best three and −50/−25/−25% in worst-first order.
- `longonly3`: +100/+65/+45% in the best three, with the extra long notional financed.
- `compare`: all three concrete strategies on exactly the same validated dataset.

Monthly decisions occur after month end, with execution at the next exchange-session close. Evaluation dates are separate from model warm-up; the response reports first execution and actual complete return periods. Fees cover both signed legs, rank changes, drift rebalancing, entry and final liquidation. Funding/borrow accrues over actual elapsed days. Insolvency is terminal. See the precise [financial model](docs/model.md) and versioned [specification](engine-spec.json) before interpreting results.

## Source and API ownership

```text
shared provider ingestion → data_mesh snapshot → radar/data.py
                                              ├─ radar/market.py
                                              └─ radar/engine.py
                                                        ↓
                                              radar/app.py → browser
```

`app.py` is the deployed FastAPI entry point. `data_mesh` remains a private Python access library; this project defines the snapshot interface its extended producer must publish. The radar does not invent a nonexistent data_mesh HTTP API or fetch paid providers on each request. See [data contract and publisher](docs/data-contract.md).

| Endpoint | Contract |
|---|---|
| `GET /api/market` | Current observations and coverage; HTTP 503 when core data is stale/unavailable |
| `GET /api/backtest` | Required `start=YYYY-MM-DD`; optional `end`, `mode`, `cost_bps`, `short_borrow_bps`, `rebalance=monthly` |
| `GET /api/health` | Data readiness, dataset identity and application version |
| `GET /api/model` | The versioned research specification |
| `GET /api/openapi.json` | Machine-readable route and parameter schema |

Costs default to 10 bps per one-way traded notional; annual short borrow defaults to 50 bps. Zero is valid. Invalid/duplicate/unknown parameters return 400 before data acquisition; unsupported methods return 405. `costBps` and `shortBorrowBps` are accepted migration aliases. No `topN` or unsupported rebalance frequency is accepted. Responses identify immutable dataset, model, requested parameters, actual period, and concrete strategy identities. Non-finite results cannot be published.

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
