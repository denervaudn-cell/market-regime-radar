# Contributor archive comparison

Reviewed: 2026-10-19 (Europe/Zurich).
Archive: `data/cracken.zip`, SHA-256 `e4bc23c6339ba71a72414e49f19aad0758639948dd025dab4b0395704c9a568d`.
Compared with source commit `6b1e466d2e475addccbb7e7eed69f2a871f938ce`.

## Conclusion

The archive contains a narrow **V4.27 historical-data/cache update**, with useful implementation intentions but no backend implementation. It does not supply a new dataset, scoring model, financial calculation, test suite, or completed fix for the earlier review. **None of the 23 existing findings can be closed on this evidence.**

Its main new proposal is to move historical ETF prices from Twelve Data to Stooq public CSV and cache the data/results. FRED public CSV and sharing one dataset across comparison modes were already described in the repository.

## Exact inventory

The ZIP has six regular entries, 132,889 bytes expanded. It was inspected directly without overwriting or extracting files into the application.

| File | Compared with repository | What changed |
|---|---|---|
| `index.html` | Changed; seven diff hunks | Four timestamp removals, one public-source/cache explanatory sentence, two cache-status labels |
| `package.json` | Byte-identical | No new packages, scripts, tests, runtime declaration, or version |
| `vercel.json` | Byte-identical | Still configures api/market.js and api/backtest.js |
| `README.md` | Nine lines appended | V4.27 historical provider/cache claims |
| `engine-spec.json` | Version plus four fields changed | Stooq/FRED sources, cache policy, historical Twelve Data independence |
| `env.example` | New | TWELVE_DATA_API_KEY and FRED_API_KEY placeholders; no real keys |

**Absent:** `api/market.js`, `api/backtest.js`, root `market.js`, root `backtest.js`, any shared provider/cache module, historical price files, and tests.

As a standalone delivery it lacks its configured API files. As an overlay on this repository it leaves the existing backend unchanged. The omission might be a packaging error or an intentional partial delivery; the archive does not establish which.

## Useful new elements

### Candidate historical source separation

Archive `README.md:226–233` and `engine-spec.json:250–253` propose:

- Stooq public daily CSV for the eleven sector ETFs and SPY.
- FRED public CSV for macro/rates/volatility/credit.
- No Twelve Data dependency for historical backtests; retain it for live dashboard modules.

This could address the Twelve Data quota problem if the missing adapter exists and the replacement data satisfies the financial contract. The archive contains no sample response or source-conformance evidence. No conclusion was reached about Stooq's actual adjustment, coverage, entitlement, or redistribution semantics.

Before substitution, verify split/dividend treatment and benchmark consistency, date/currency semantics, complete histories, missingness, source availability, and reproducible dataset identity. A provider change must not silently change a total-return backtest into a different return basis.

### Candidate caching policy

Archive `README.md:231` and `engine-spec.json:252` propose a six-hour warm-instance cache and six-hour HTTP cache with 24-hour stale-while-revalidate.

This is relevant to earlier finding **#11: provider consumption and dataset reuse**. It is a specification only. The current routed handler still sets `Cache-Control: no-store` at `api/backtest.js:89`, requires Twelve Data at lines 90–92, and contains no Stooq loader.

Warm-instance memory and HTTP/CDN response caching are distinct. Vercel reuses instances but can scale them down; therefore a configured in-memory TTL alone is not evidence of durable shared retention. Cache behavior needs deployed verification and a defined freshness policy. [Vercel function lifecycle](https://vercel.com/docs/functions), [Vercel CDN caching](https://vercel.com/docs/caching/cdn-cache).

Prefer reusing validated historical datasets across strategy calculations. Specify source/data version, asOf, fetchedAt, cache age, refresh/failure handling, and in-flight coalescing. Response-cache identity must include every financial parameter and calculation version. A cache hit does not establish current market data.

### Environment example

The new three-line `env.example` is useful setup scaffolding. It lists placeholder keys only. It still needs documentation matching the actual endpoint requirements: current market requires both keys; current backtest requires Twelve Data and gets FRED through public CSV.

## Actual UI changes and compatibility

| Archive location | Delta | Result against current backend |
|---|---|---|
| `index.html:363` | Claims public historical prices cached server-side | Unsupported by delivered files and current routed API |
| `index.html:1610,1784,1885,1917` | Removes the four timestamp cache-busting parameters | Useful preparation; no server cache is created |
| `index.html:1897` | Adds `cache ${d.meta.cache}` to Long Only status | Current metadata has no cache field, so it displays `cache undefined` if the run renders successfully |
| `index.html:1963` | Adds `cache ${payload.meta.cache}` to Compare status | Assumes a new contract; current Compare already fails earlier on missing nested results |

All four request paths retain `cache:"no-store"` at archive lines 1611, 1785, 1887 and 1918. Browser fetch caching and CDN/server caches require separate treatment; removing the timestamp alone cannot establish the promised server behavior.

The frozen Risk Bias, static/synthetic analytical panels, duplicate chart ownership, stale-result handling, unsupported routed strategies and unversioned Chart.js are unchanged.

## Specification contradictions

The new Stooq/no-key fields coexist with unchanged statements in the same archive:

- `engine-spec.json:168`: Twelve Data historical prices.
- `engine-spec.json:226`: Twelve Data `adjust=all`.
- `engine-spec.json:231–233`: required TWELVE_DATA_API_KEY.
- `engine-spec.json:165–166`: illustrative performance alongside REAL DATA ONLY.

There is no change to factors, weights, universe, exposures, costs, point-in-time behavior, statistical formulas, or out-of-sample validation. Earlier findings **#18 (model specification)** and **#23 (current documentation)** remain directly relevant.

## Recommended use

Retain the historical-source/cache proposal and environment example as requirements for the next implementation. Do not treat the new UI wording as evidence that V4.27 is operational.

The useful next delivery from the contributor is the complete V4.27 source or commit, especially the actual `api/backtest.js` and any shared source/cache modules, with sample output and tests. Then verify:

1. Long Only/Compare contracts and strategy identity.
2. Historical price/total-return conformance and missing-data rules.
3. Warm/cold cache behavior, parameter isolation, freshness and failure handling.
4. The existing financial regression cases from [health.md](health.md).

Switching providers and adding a cache will not by themselves correct transaction costs, missing-period deletion, same-close information timing, Sharpe, or leverage accounting.

## Validation and change scope

Compared every ZIP entry with the corresponding repository file, inspected all seven HTML diff hunks, parsed all three JSON files, and syntax-compiled all four inline scripts without executing them. Two independent reviewers assessed UI and methodology/specification changes.

No contributed script was executed, no application file was replaced, and no historical provider data was downloaded. Public documentation was checked for cache semantics. This addendum and a link from the main review are the only changes from this follow-up; the existing findings and IDs are preserved.
