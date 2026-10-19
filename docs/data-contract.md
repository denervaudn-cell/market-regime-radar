# data_mesh distribution contract

The radar consumes **one immutable JSON snapshot**, produced by the future extended data_mesh distribution. It does not call Bloomberg, FMP, Twelve Data or FRED while rendering a dashboard or running a backtest. The missing upstream onboarding and historical-vintage work remain outside this repository. No synthetic production fallback exists.

## Required observations

| Family | Identifiers | Convention |
|---|---|---|
| ETF quoted closes | SPY, QQQ, GLD, USO, UUP, XLB, XLC, XLE, XLF, XLI, XLK, XLP, XLRE, XLU, XLV, XLY | `price_basis: close`, `unit: USD`, `currency: USD` |
| ETF return indices | All 16 identifiers above with `_TR` suffix | `price_basis: total_return_net` **or** `total_return_gross`, `unit: index`, `currency: USD` |
| Treasury yields | DGS2, DGS5, DGS10, DGS30 | `price_basis: rate`, `unit: percent` |
| Real yield, inflation expectation, high-yield spread and funding | DFII10, T10YIE, BAMLH0A0HYM2, DFF | `price_basis: rate`, `unit: percent` |
| Volatility | VIXCLS | `price_basis: index`, `unit: index` |

This is 41 series: 16 quoted closes, 16 total-return indices and 9 macro series. The backtest requires the eleven sector `_TR` series plus SPY_TR; market analytics require the eight displayed ETFs and their separate `_TR` series. ETF exposures are labelled as ETFs: USO is not spot oil, UUP is not a direct USD index, and SPY is not the index itself.

Quoted closes are displayed as prices. Daily/20-session changes, z-scores, percentiles and correlations use total-return histories, so splits and distributions do not create artificial signals. There is no fallback from total return to quoted prices. All histories within one calculation must share the same net/gross convention. A Bloomberg net-dividend return index is not interchangeable with a gross-dividend series or a provider's unspecified “adjusted close.” Normalize upstream only after verifying the source field semantics.

Optional inputs enable additional panels:

- `VIX9D`, `VIX3M`, `VIX6M`, `VIX1Y`, `VVIX`, `SKEW`, `MOVE`: `price_basis: index`, `unit: index`. Use the actual index instruments, not ticker-prefix matches to unrelated equities.
- `EURUSD`, `USDJPY`, `USDCHF`, `GBPUSD`, `AUDUSD`, `USDCAD`, `USDCNH`, `AUDJPY`: `price_basis: fx`, `unit: QUOTE/BASE`; for example EURUSD has `unit: USD/EUR`. Inversions/crosses must be calculated upstream from aligned observation and availability times, with that provenance in `source`.
- `TLT`, `CPER` and their separate `_TR` indices: the same USD close/return conventions as the core ETFs. TLT is the long-Treasury ETF proxy; CPER is a copper-futures fund proxy, not a spot copper quote.
- `T5YIE`, `T5YIFR`: rate/percent series for five-year breakeven and five-year forward inflation compensation. Supply the actual five-year-forward series; a linear difference is only an approximation.

The complete preview universe has **62 series** (41 core + 7 volatility + 8 FX + 4 bond/copper + 2 inflation). Full V4 research coverage needs these extended inputs and enough prior daily history for normalization. The publisher still permits core-only feeds; missing extended evidence produces explicit partial/unavailable research sections. Analytics formulas, units and history requirements are in [analytics.md](analytics.md).

### Explicit source provenance and mock inputs

Snapshots may include `source: {"kind":"mock","label":"Synthetic market inputs · seeded preview v1","seed":8042}`. The real form uses `kind:"real"` and a descriptive label, with no generator seed. Metadata is validated, immutable and included in the content hash. Existing snapshots without this optional field retain their original hash convention; the API labels them as configured real snapshots. Source metadata is a producer declaration, not cryptographic authentication.

`RADAR_DATA_MODE=mock` explicitly selects the seeded generator. It produces only observations through the last completed publication cutoff and passes exactly the same snapshot validation; analytics/backtests never receive hardcoded display scores. The generated series all carry MOCK source labels. Every market/analytics/backtest/studies/health response and UI export preserves the mock kind and seed. A configured real source cannot silently switch to mock inputs on failure. The mock generator preserves quote/total-return separation, coherent FX crosses and the compounded five-year-forward inflation relationship, but its observations are not historical market data.

## JSON envelope

The following is an illustrative shape, not an executable production sample:

```json
{
  "schema_version": 1,
  "dataset_id": "sha256:<64 lowercase hexadecimal characters>",
  "generated_at": "2026-10-16T23:00:00Z",
  "as_of": "2026-10-16",
  "calendar": ["2026-10-15", "2026-10-16", "2026-10-19"],
  "series": {
    "SPY_TR": {
      "id": "SPY_TR",
      "source": "provider / instrument identifier / field / vintage policy",
      "unit": "index",
      "currency": "USD",
      "price_basis": "total_return_net",
      "observations": [
        {"date": "2026-10-16", "value": 100.0, "available_at": "2026-10-16T21:00:00Z"}
      ]
    }
  }
}
```

`date` is the economic observation date; `available_at` is when that specific value/version became usable by the consumer. `generated_at` describes snapshot creation, not observation freshness. All timestamps require explicit time zones and normalize to UTC. Each series must be sorted by `(date, available_at)`, with no duplicate pair. Multiple revisions of the same observation date are supported. No observation may lie after `as_of`, and no version may become available after `generated_at`.

Historical backtests need real availability and revision records. A present-day FRED download cannot be turned into a point-in-time ledger by assigning each value its observation date. The publisher never fabricates availability times; exporting only the latest revisions with honest current availability will correctly make earlier simulations unavailable. Source/vintage correctness is an upstream responsibility that structural validation cannot independently establish.

`calendar` is the complete ordered NYSE session list covering the supplied ETF histories. Include at least the next 30 calendar days of sessions beyond the publication date so the market service can distinguish weekends/holidays from missing updates. Future calendar sessions are metadata, not future observations. The consumer independently compares the complete list with the locked `exchange_calendars` XNYS calendar and rejects omitted or invented sessions. Supported calendar bounds are 1990 through two years beyond today; maximum calendar length is 20,000 sessions. ETF observations outside the supplied sessions are invalid. Calendar-only sessions after `as_of` never become backtest returns.

The ID is SHA-256 over normalized content excluding `dataset_id`: sorted object keys, compact JSON, normalized UTC timestamps, numeric values as floats and explicit model defaults. Use `radar.data.dataset_content_id(payload)` rather than hand-implementing canonicalization. It identifies content; it is not a signature or proof of origin. Snapshot models are frozen, observation/calendar collections are tuples, and the series mapping is immutable.

## Validation and publication

The boundary rejects unknown fields, duplicate JSON keys, blank/missing markers, numeric strings, booleans and non-finite values. Missing observations must be absent, not silently changed to zero. Rates permit genuine zero and negative values within -100 to 1,000 percentage points; prices, FX and indices must be positive and no larger than 10^15. Units/bases must be explicit. Limits are 80 series, 30,000 observations per series, 250,000 total observations, 120 source-label characters and 32 MiB serialized input. Full daily histories and historical revisions must fit these limits; partition/export the needed research range upstream when necessary.

Publish a real exporter output locally:

```bash
uv run python scripts/publish_dataset.py /secure/exports/radar.json /secure/radar/current.json
```

The script adds the content ID if absent, verifies the entire snapshot, requires all 41 series by default, and then writes an immutable `versions/<hash>.json` plus an atomically replaced `current.json`. Previously published current content remains intact after validation failures. `--allow-partial` supports deliberate onboarding; absent inputs remain unavailable in the app. Presence validation is not a guarantee of full research coverage: the engine separately enforces its requested warm-up, availability and calendar coverage.

The script performs no external API/DB calls and does not guess a nonexistent data_mesh macro endpoint. The upstream exporter should resolve the instrument registry, fetch approved price/return fields, preserve macro vintages and availability, and emit this contract. Store exports outside the public static directory and outside tracked source control. Do not mutate a version file in place; publish a new content ID.

## Acquisition and freshness

Set exactly one server-side source:

```bash
RADAR_DATASET_PATH=/secure/radar/current.json
# Or: RADAR_DATASET_URL=https://your-distribution-host/private/radar/current.json
# Optional for that URL: RADAR_DATASET_TOKEN=<server-side bearer token>
```

Remote URLs require HTTPS, have no embedded user/password, and are fixed by server configuration. Public query parameters cannot select a source. Redirects are not followed, including when an externally supplied HTTP client would normally follow them. Tokens are sent only in the Authorization header, never returned to the UI. Signed HTTPS URLs are also possible; treat their configuration as a secret. Deployment must restrict access to the trusted source and confirm the existing display entitlement.

The default store budget is a 10-second end-to-end acquisition deadline, 5-second HTTP operation timeouts, two retries after the initial GET, one connection/in-flight snapshot acquisition and a 300-second validated cache. Transient 429/500/502/503/504 and transport failures may retry with bounded exponential backoff and jitter. Both forms of Retry-After are honored; a requested delay beyond the remaining budget fails without retrying early. HTTP requests send `Accept-Encoding: identity`; the fixed distribution endpoint must serve uncompressed JSON. Any nonidentity Content-Encoding is rejected before the body is read, preventing decompression from allocating beyond the acquisition budget. Accepted bodies are streamed in 64 KiB chunks under the 32 MiB byte cap. Local sources must be regular files, not pipes/devices.

Concurrent callers share acquisition. Cancelling one caller preserves work needed by others; cancelling the final caller cancels the fetch. Blocking file reads and validation run in owned workers off the event loop. A timed-out worker remains owned until exit, and replacement loads fail busy instead of accumulating threads. Shutdown joins these owned workers. Cached expired content is never returned as successful recovery after refresh failure. A still-valid cache never overrides observation-level freshness.

The market service uses the last completed XNYS session with a conservative 16:30 America/New_York publication cutoff, also on early-close dates. Quoted ETF and return-index observations must match that session. Macro observations permit at most three calendar days of lag from it. A calendar that no longer covers the current date makes publication unavailable. Fresh generation timestamps cannot conceal stale observations. Per-series metadata carries observation time, availability time, source, status and reason; partial or stale feed outcomes are distinct from ready.

Correlations join identical consecutive exchange-session **start and end dates** within the last 20 completed sessions, requiring at least 15 common observations and nonzero variance. Missing intermediate prices cannot become a one-day return across a gap. Daily z-score/percentile use the current total return against 60–260 prior daily returns; percentile uses midrank ties. Curve spreads join a common observation date. Optional panels contain only supplied/derived data; missing views are explicitly unavailable.

The basic `/api/market` endpoint supplies observations. `/api/analytics` supplies documented multi-horizon risk and regime research rules using actual inputs. These rules replace the old placeholder formula as an explicit, versioned implementation; their strength is not a forecast probability, and empirical model validation remains outstanding.
