# PLAN: Market Regime Radar revamp

Started: 2026-10-19. Status: signal-oriented visual redesign complete; V5 core and V4 feature restoration verified.

## Completed phase: signal-oriented visual redesign (2026-10-19)

Preserve all calculated features and the new UI structure while restoring V4's vivid semantic palette and clearer focus. Color must distinguish direction, unusual magnitude and data availability, never manufacture an alert from ordinary observations. Keep mock provenance explicit.

- [x] Inspect V4 visual language and current calculated payloads.
- [x] Put horizon direction, divergence and the strongest observed signals first; move technical provenance into inspectable detail.
- [x] Rework palette, hierarchy, tables and responsive layouts around signal strength.
- [x] Upgrade charts with bright distinct series, readable units and accessible point inspection.
- [x] Verify existing browser behavior, signal formatting, unavailable states, desktop/tablet/mobile layouts and keyboard access.
- [x] Record verification and commit the local redesign.

Ownership: root owns HTML and application presentation; signal_styles owns app.css; signal_charts owns new charts.js/charts.css. Financial models, source data and API contracts remain unchanged.

Verification: 17 browser tests passed, including new direction/severity, stale highlight clearing, percentage units, keyboard/pointer inspection and missing-value chart checks. Ruff lint/format, both JavaScript syntax checks and diff checks passed. Actual Python mock API exercised all ten analytics families and weekly Top-5 three-strategy comparison (13 research charts, including 63 annual bars), with no console errors or page overflow. Visual checks covered 320, 390, 768, 1024 and 1440px widths; the in-app preview was refreshed and inspected. No new dependencies or backend/model changes.

## Completed phase: complete V4 analytical coverage (2026-10-19)

User explicitly requested every missing V4 feature, preservation of the new UI, real calculations and mock inputs for now. This supersedes the earlier decision to leave research panels unavailable. Mock data must be explicit, reproducible, identified in every API result/export and visually labelled; it must never silently replace a failed real source.

- [x] Compare original V4 source and release history against current functionality; identify computed regressions and former demo-only panels.
- [x] Define implementation ownership and integration contracts below before editing application code.
- [x] Restore annual/benchmark statistics, rotation and ranking diagnostics, drawdown/rolling return series and attribution.
- [x] Implement weekly/monthly/quarterly schedules, ranked Top-N, bounded robustness/cost-sensitivity/regime studies.
- [x] Implement full rates, volatility, FX and correlation analytics using dated observations.
- [x] Implement current sector/factor/style views, multi-horizon risk/divergence, anomalies/changes, historical matches and rule-based narratives/playbook.
- [x] Build deterministic mock snapshot generator and explicit mock source mode using the production snapshot contract.
- [x] Extend the new UI to display all restored calculations, provenance and mock labels.
- [x] Add meaningful calculation, boundary, API and browser regression checks; verify real Python API with the mock feed.
- [x] Update feature-parity matrix, formulas, data requirements, runbook and final verification evidence; commit locally.

### Final restoration verification

2026-10-19: 182 Python tests, 14 browser tests and 3 Node compatibility tests passed. Ruff lint/format, JavaScript syntax, dependency audits and diff checks passed. Actual Python API browser smoke exercised all ten analytical sections, weekly Top-5 comparison, quarterly Top-2, all thirteen study scenarios, JSON exports, desktop and mobile layouts. Independent review fixed cross-date volatility combinations, UTC/New York observation retention, short/flat-history readiness and a work-budget shutdown race. Empirical model validation and the real shared producer remain external; functional panels no longer depend on hardcoded demo outputs.

### Integration contracts and ownership

- Financial agent owns `radar/engine.py`, `radar/studies.py`, engine/studies tests, `docs/model.md`, `engine-spec.json`. Extend existing response additively. `run_studies(dataset, params)` is a separate bounded request. Weekly/quarterly still use month-end-trained macro normalization and the same next-session execution discipline; report frequency-correct statistics. Ranked basket accepts `top_n` 1–5, with half on rank 1 and equal remainder (one rank gets 100%). Fixed extreme and long-only exposures stay explicit.
- Market analytics agent owns `radar/analytics.py`, analytics tests, `docs/analytics.md`. `market_analytics(dataset, now=None)` returns `{ok,status,dataset_id,as_of,model_version,sections}`. Each section has `{status,title,summary,metrics:[{label,value,unit}],tables:[{title,columns,rows}],charts:[{title,unit,series:[{label,points:[{date,value}]}]}]}`. Numeric missingness is null with explanation. Sections: `risk`, `changes`, `anomalies`, `correlations`, `rates`, `volatility`, `fx`, `sectors`, `playbook`, `analogues`.
- Frontend agent owns `index.html`, `static/`, `tests/ui.spec.js`. Preserve styling, add section navigation/progressive disclosure and `/api/analytics`, `/api/studies`. Existing `/api/market` remains the observation overview. Generic section renderer makes analytical results inspectable without hardcoded financial values.
- Root owns API, mock input generator/mode, snapshot provenance extension, integration tests, docs outside agent ownership and final QA. `/api/analytics` and `/api/studies` share bounded work/cache; source provenance `{kind:mock|real,label,seed?}` travels on all responses. No live source is overwritten. Mock mode selected explicitly with `RADAR_DATA_MODE=mock`.

### Completion standard

Every historical feature family must have implemented calculations and a visible result in the mock preview. Composite regimes/conviction are documented deterministic research rules, never investment probabilities; historical forward outcomes exclude incomplete windows and noncausal feature selection. Producer integration and empirical validation remain external, but are not reasons to omit the requested research implementations.

## Original core phase: scope and recovery (completed)

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

## Original core-phase decisions (superseded where noted above)

- data_mesh remains the source boundary; its missing upstream series and a production deployment are not assumed complete.
- Synthetic datasets belong only to tests or an explicitly labelled local preview, never an automatic production fallback.
- Backtests require dated availability and complete daily histories, use monthly decisions and later executable closes, and report their actual evaluation dates.
- Unsupported fixture analytics will become honest unavailable states, with real derived panels implemented where the validated dataset supports them.
- Research scores remain unvalidated and non-prescriptive until domain review and out-of-sample evidence exist.
