# Operation, verification and recovery

## Data publication

The shared data producer owns provider entitlements, instrument mappings, original observation/availability timestamps, revisions, quoted-price and total-return semantics, and scheduled refresh. The radar consumes that distribution; it makes no direct Twelve Data/FRED/FMP/Bloomberg requests. `data_mesh` upstream extensions are not implemented in this repository.

Publish a validated snapshot atomically using `scripts/publish_dataset.py` (see `--help` and [data contract](data-contract.md)). Configure one source: `RADAR_DATASET_PATH` locally or `RADAR_DATASET_URL` for a fixed HTTPS distribution endpoint. Use a server-side token if the distribution endpoint requires it. Never expose shared database/provider credentials in browser JavaScript.

Production snapshots must contain actual availability metadata. A current download of historical values is not automatically point-in-time history. Do not fabricate earlier publication timestamps to make a backtest pass. The consumer fails explicitly on insufficient warm-up, missing dates/instruments, incompatible return conventions, or unavailable historical observations.

Snapshot acquisition has a 10-second default overall I/O deadline, five-second network-operation timeout, one in-flight source acquisition per process, at most three total attempts, a 32 MiB response budget, and a five-minute validated-data cache. Expired data is not returned as success after a refresh failure. Current freshness is recomputed from observation dates and the exchange calendar, not the cache timestamp. The package validates NYSE holidays and session coverage independently with exchange_calendars.

Calculations have two worker slots per process and a 15-second reader budget. A timed-out read-only calculation retains its slot until it finishes; threads cannot safely be killed. It cannot create unbounded replacement work. Results are coalesced by dataset/parameters and kept as immutable encoded values in a 16-entry, 2 MiB-per-result cache. Dataset changes invalidate this identity naturally. These are per-process budgets; configure existing platform concurrency/rate controls before public deployment. There are no paid upstream calls to amplify through the research endpoints.

## Readiness and errors

`GET /api/health` checks current core-market readiness. Missing configuration/data and stale coverage return 503, never demo success. This differs from process liveness: the HTML can be served while the dataset is unavailable. `GET /api/market` preserves explicitly labelled partial/stale observations in its 503 body. Backtests can validly use historical snapshots even when those snapshots are unsuitable for a current market view.

Investigate stable error codes and the `X-Request-ID` response header. Request-completion logs include method/path, duration and HTTP outcome; no provider URL, authentication token or raw dataset is logged. Failure responses use `Cache-Control: no-store`. The current ready-market response allows only a 30-second private browser cache. Backtest result caching is internal and tied to immutable dataset identity.

Common outcomes:

| Outcome | Operator action |
|---|---|
| `dataset_not_configured` | Configure the published file or HTTPS URL |
| `invalid_dataset` | Run the publisher validation and inspect field/type errors; correct upstream data |
| `missing_series`, `missing_history`, `missing_macro_history` | Backfill exact required inputs and availability metadata; do not forward-fill silently |
| `insufficient_warmup` | Supply earlier history or explicitly choose a supported evaluation period |
| Market stale/calendar out of range | Refresh observations/calendar and inspect producer completion |
| `dataset_upstream_unavailable`, `dataset_timeout` | Inspect shared distribution health and bounded retry timing |
| `busy` (429) | Respect Retry-After and existing platform capacity controls |
| `calculation_timeout` | Inspect input size and service capacity; do not bypass completeness checks |
| `ruined` strategy result | Valid terminal research outcome; the engine does not continue trading negative NAV |

No production alert destination or standing deployment identity was established during implementation. Before enabling production, connect `/api/health` and structured logs to the team's existing monitor, name the operational owner and response destination, and verify a missing/stale dataset alert there. No external monitoring task was silently created.

## Verification and release

```bash
uv sync --locked
npm ci
npm run check
npm test
npm run test:legacy
uv run pip-audit
npm audit
npx playwright install chromium
npm run test:ui
```

Tests use synthetic, named fixtures without live provider/database calls. Financial cases cover signed legs, rank/drift turnover, timing/revisions, warm-up, missing dates, early closes, funding, excess-return Sharpe and insolvency. HTTP cases exercise the actual Python entry path and explicit mode payload. Playwright exercises browser lifecycle and safe status rendering. CI runs the same checks with locked dependencies and pinned action revisions.

Vercel uses root `app.py` with its FastAPI framework and a 30-second function ceiling. Official deployment documentation: [FastAPI](https://vercel.com/docs/frameworks/backend/fastapi), [Python runtime](https://vercel.com/docs/functions/runtimes/python). Clear any old dashboard-level build/runtime overrides when migrating the deployment. The app serves only the root HTML and `static/`; repository sources, snapshots and contributor archives are not public routes. `.vercelignore` excludes local data, tests, credentials, caches and archives.

Before production publication, run a routed preview against an approved real snapshot and verify sources, dates, all three strategies, failure states, and telemetry. Record the actual source commit, platform deployment ID, resolved Python/Node versions, dataset ID and rollback deployment. Local tests do not establish a deployed artifact's behavior or a model's investment efficacy.

## Rollback

The annotated tag **`pre-revamp-2026-10-19`** points to main commit **`6b1e466d2e475addccbb7e7eed69f2a871f938ce`** and was pushed to origin before source changes. It identifies the old V4 code, including its documented defects.

To inspect or deploy the baseline without resetting another checkout's work:

```bash
git fetch origin tag pre-revamp-2026-10-19
git worktree add --detach ../market-regime-radar-baseline pre-revamp-2026-10-19
```

For a deployed rollback, prefer the platform's previously verified deployment if retained. Restoring V4 also restores its Node/Vercel configuration and requires the old Twelve Data and FRED environment setup. This revamp makes no shared database migrations; the tag does not roll back shared data producers, provider accounts, external configurations or untracked files.

The root `market.js` and `backtest.js` remain thin compatibility handlers for unknown existing Node imports. They require `RADAR_PYTHON_API_URL`, accept GET only, and proxy to the canonical Python service with a deadline/response-size bound. They contain no financial calculations. Old `api/*.js` Vercel functions are removed to prevent competing routes.
