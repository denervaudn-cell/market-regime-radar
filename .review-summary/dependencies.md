# Dependencies, security, and operations

Evidence date: 2026-10-19 (Europe/Zurich). Reviewed commit: `6b1e466d2e475addccbb7e7eed69f2a871f938ce`.

## Dependency inventory

The application declares **zero npm dependencies**. It still has executable and operational dependencies outside that manifest.

| Component | Observed contract | Assessment |
|---|---|---|
| Node.js | package engines >=20; ESM/native fetch | Actual deployed runtime unknown; review host was v24.5.0 |
| Chart.js | `https://cdn.jsdelivr.net/npm/chart.js` | Unversioned CDN script, no SRI or manifest record; resolved to 4.5.1, 208,522 bytes during review |
| Vercel CLI | `dev: vercel dev` | Not declared as devDependency; fresh setup depends on global tooling |
| Vercel Functions/CDN | api/ routing, 30/60-second ceilings and cache headers | Actual project access rules, deployed runtime/artifact and monitoring were not inspected |
| Twelve Data | Daily ETF prices; historical backtest requests adjust=all | Requires key and suitable entitlement; exact licensed coverage/redistribution and rate budget unverified |
| FRED API | Four live Treasury series | Requires FRED_API_KEY on current market path |
| FRED CSV | Seven historical macro/funding series | No key; full-history download on each historical request |

No transitive npm dependency tree exists in the manifest. Consequently an empty npm audit/lockfile would not assess the actual Chart.js CDN code or globally installed development tooling. No unused npm packages or competing HTTP libraries were found.

## Advisory applicability

The known [Chart.js CVE-2020-7746 advisory](https://github.com/advisories/GHSA-h68q-55jf-x68w) applies below 2.9.4 and does **not** apply to the observed 4.5.1 response. The [maintainer advisory page](https://github.com/chartjs/Chart.js/security/advisories) did not list a published maintainer advisory during review. These checks do not guarantee absence of vulnerabilities; dependency identity and tested release reproducibility are the concrete repository gap.

The manifest's >=20 range does not prove that production runs Node 20. [Vercel's runtime documentation](https://vercel.com/docs/functions/runtimes/node-js/node-js-versions) lists supported majors and managed updates; a wide range may select the newest supported major. [Node's release lifecycle](https://nodejs.org/en/about/previous-releases) lists Node 20 as end-of-life by this evidence date. Refresh the documented support contract and record the actual deployment runtime.

The local review host v24.5.0 predates the [July 2026 Node security release](https://nodejs.org/en/blog/vulnerability/july-2026-security-releases). This is a host observation, not proof of vulnerable deployed application behavior. Several advisory primitives are absent from this application's source. Verify the actual runtime and relevant exposure rather than attributing every Node CVE to this repository.

Recommended dependency policy: use authoritative package/build records, record the exact browser artifact with integrity or bundle it, exercise the release artifact, and keep adopting compatible updates. Do not create indefinite version freezes.

## Provider consumption and performance

A mocked historical request executes **19 upstream fetches concurrently**: 12 price histories and seven macro/funding histories. Repeating a request repeats acquisition; parameter changes could reuse the same dated dataset. There is no observed CPU bottleneck requiring optimization before correctness fixes. Fixture runs with artificial provider latency are not real performance benchmarks.

One anonymous public DFF CSV request returned **424,315 bytes / 26,406 lines**, beginning 1954-07-01. The current universe begins in 2018. Provider-supported date bounds and reusable datasets can reduce unnecessary transfer while preserving normalization/momentum warm-up. This is a payload measurement, not a measured end-user latency improvement.

[Twelve Data's credit documentation](https://support.twelvedata.com/en/articles/5615854-credits) charges time-series work per symbol. Actual account credits, concurrency, billable behavior and caching/redistribution permission were not inspected. Apply limits to the real plan rather than inventing universal budgets.

Both handlers accept methods without an application method allowlist. Historical requests are no-store; browser timestamps defeat request reuse. Market's CDN cache helps ordinary GET traffic but is not an admission limit, and [Vercel cacheability criteria](https://vercel.com/docs/caching/cdn-cache#cacheable-response-criteria) exclude POST.

## Security posture and bounded observations

- Keys are read server-side; no hardcoded credential was found in inspected application source or browser code.
- Provider destinations and symbols are fixed, and query strings are built with URLSearchParams. No user-controlled fetch destination was found.
- There are no scoped application accounts, payments, database, file uploads, subprocesses, or intentional client-identity storage. Do not invent session, CSRF, SQL, or file-upload requirements for capabilities the product lacks.
- Public accessibility and configured Vercel firewall/protection remain unknown. The confirmed issue is unbounded application work per accepted request, not proof that an attacker can reach a particular deployment.
- Price-provider credentials are placed in URL parameters. The guideline default is a provider-specific secret header where supported; otherwise document the exception and redact URLs. Confirm the endpoint's header contract before changing it. No actual secret-log disclosure was established.
- External error text crosses into HTML through provider-message propagation and UI error table sinks at index.html:1849,1898,1964. An independent attacker-controlled source was not established, so this review does not claim a demonstrated remote XSS. Use textContent/DOM construction for error text and return stable sanitized error codes.
- Repository configuration contains no custom security-header policy. Actual production response headers were not observed; their absence at deployment is not established.
- A .gitignore and .env.example are absent. Add appropriate secret/local-state exclusions and documented variable names when establishing supported setup; do not infer that a secret has already leaked.

## Failure behavior

Market failures can return HTTP 200 DEMO_FALLBACK with live-style cache policy. Mode labels are useful, but a [long-lived cache policy](https://vercel.com/docs/caching/cache-control-headers) can preserve fallback after recovery. Both functions lack application-level structured request/provider outcomes. External monitoring may exist; it was not inspected.

No fetch deadlines or cancellation policy exists. In the mocked early-failure probe, 18 sibling requests remained active when the error was returned. Platform duration ceilings do not replace graceful request budgets or cancellation.

## Release evidence to obtain after repairs

Verify the routed preview and deployed source identity; resolved dependencies/runtime; actual environment requirements per endpoint; one successful and one degraded provider path; date/coverage/adjustment assertions; observable logs and failure signals; and effective provider/access budgets. Reuse existing deployment facilities. A new monitoring platform, account system, or recurring job is not mandated by this review.
