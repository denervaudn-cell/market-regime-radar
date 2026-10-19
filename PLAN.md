# PLAN: Market Regime Radar revamp

Started: 2026-10-19. Status: implementation and local verification complete.

## Scope and recovery

Implement the 23 findings in IMPROVEMENTS.md against a future extended data_mesh distribution contract. Do not fabricate missing market data or change other repositories. Preserve the supplied archive. Application deployment and an investment model's empirical validation are separate from implementing and testing the code.

- [x] Verify main baseline and remote identity.
- [x] Create and push annotated rollback tag `pre-revamp-2026-10-19` at `6b1e466d2e475addccbb7e7eed69f2a871f938ce`.
- [x] Create implementation branch `codex/radar-revamp`.

## Design

- [x] Choose one Python financial engine and one API contract; retain a small static frontend.
- [x] Use validated, immutable data_mesh JSON snapshots; no paid-provider calls per dashboard request.
- [x] Preserve legacy score coefficients as explicitly unvalidated research assumptions. Do not silently alter investment meaning or publish calibrated-probability claims.
- [x] Finalize schemas, model specification, exact timing, financing, missingness and terminal-state rules.

## Implementation

- [x] Data snapshot models, strict validation, bounded acquisition/cache and data_mesh publication interface.
- [x] Canonical Python engine: explicit modes, point-in-time selection, warm-up, costs, statistics, terminal behavior and independent reference tests.
- [x] Market analytics: dates, freshness, valid correlations and observed risk inputs; unsupported directional score explicitly withheld.
- [x] One frontend state/render lifecycle, immutable runs, explicit unavailable panels and supported controls only.
- [x] Routed API, HTTP validation, telemetry, static serving, reproducible dependencies and CI.
- [x] README, data contract, model specification, rollback/runbook and finding-by-finding remediation record.

## Verification

- [x] Run offline engine, data and HTTP integration tests: 115 Python tests and 3 Node compatibility tests passed.
- [x] Run lint/format and dependency checks on the resolved artifacts: passed; no known dependency vulnerabilities reported.
- [x] Run real-browser checks for repeated runs, failures, parameter changes and file-mode guidance: 9 passed, plus a local synthetic-snapshot smoke through the actual Python API.
- [x] Review cross-component integration and address discovered defects, including timeout ownership, shutdown draining and compressed response rejection.
- [x] Update all 23 finding statuses with evidence and disclose external dependencies in REMEDIATION.md.

## Remaining external work

The real data_mesh producer/backfill, empirical investment-model validation and production deployment/monitoring remain external prerequisites. No production deployment or shared-data migration was performed. Finding 18's code consistency and disclosure are implemented; its economic validation is unresolved.

## Decisions

- data_mesh remains the source boundary; its missing upstream series and a production deployment are not assumed complete.
- Synthetic datasets belong only to tests or an explicitly labelled local preview, never an automatic production fallback.
- Backtests require dated availability and complete daily histories, use monthly decisions and later executable closes, and report their actual evaluation dates.
- Unsupported fixture analytics will become honest unavailable states, with real derived panels implemented where the validated dataset supports them.
- Research scores remain unvalidated and non-prescriptive until domain review and out-of-sample evidence exist.
