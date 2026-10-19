import { test, expect } from '@playwright/test';
import { pathToFileURL } from 'node:url';
import path from 'node:path';

const modes = ['extreme1', 'ranked3', 'longonly3'];
const mockSource = { kind: 'mock', label: 'Synthetic test inputs', seed: 8042 };

test.beforeEach(async ({ page }) => {
  await page.route('**/api/analytics', (route) => route.fulfill({ json: { ok: true, dataset_id: `sha256:${'b'.repeat(64)}`, as_of: '2026-10-16', model_version: 'test-analytics', sections: {} } }));
});

function marketFixture(overrides = {}) {
  return {
    ok: true, status: 'ready', dataset_id: `sha256:${'b'.repeat(64)}`, as_of: '2026-10-16', generated_at: '2026-10-17T08:00:00Z',
    assets: [{ symbol: 'SPY', label: 'S&P 500 ETF', latest: 620.25, change_1d: .012, change_20d: -.021, z_1d: .4, percentile: 60, source: 'Test source', as_of: '2026-10-16', status: 'ready' }],
    rates: [{ tenor: '10Y', value: 4.25, source: 'FRED', as_of: '2026-10-16', status: 'ready' }],
    correlation: { labels: ['SPY', 'QQQ'], matrix: [[1, null], [null, 1]], sample_sizes: [[20, 3], [3, 20]] },
    risk_bias: { label: 'Model review required', score: null, status: 'unavailable', explanation: 'Composite weights require review.', factors: [{ id: 'vix', label: 'VIX', value: 19.35, unit: 'index', source: 'FRED', as_of: '2026-10-16', contribution: null }] },
    panels: { fx: { status: 'unavailable', reason: 'FX observations are missing.', items: [] } },
    metadata: { expected_session: '2026-10-16', calendar_status: 'ready', series: [{ id: 'SPY', source: 'Test source', as_of: '2026-10-16', available_at: '2026-10-16T22:00:00Z', status: 'ready', reason: null }] },
    ...overrides,
  };
}

function runFixture(url, datasetId = `sha256:${'a'.repeat(64)}`, cagr = .064) {
  const query = new URL(url).searchParams;
  const params = { start: query.get('start'), end: query.get('end'), mode: query.get('mode'), cost_bps: Number(query.get('cost_bps')), short_borrow_bps: Number(query.get('short_borrow_bps')), rebalance: query.get('rebalance'), top_n: Number(query.get('top_n')) };
  const results = {};
  for (const mode of params.mode === 'compare' ? modes : [params.mode]) {
    results[mode] = {
      strategy: { id: mode, label: `Test ${mode}`, long_gross: mode === 'longonly3' ? 2.1 : mode === 'ranked3' ? 1 : 2, short_gross: mode === 'longonly3' ? 0 : mode === 'ranked3' ? 1 : 2, gross: mode === 'longonly3' ? 2.1 : mode === 'ranked3' ? 2 : 4, net: mode === 'longonly3' ? 2.1 : 0 },
      status: 'complete',
      stats: { total_return: .12, cagr, annualized_volatility: .1, sharpe: .5, max_drawdown_monthly: -.04, hit_rate: .6, annualized_turnover: 2.2, benchmark_total_return: .08, periods: 12, metric_status: {} },
      equity_curve: [{ date: '2020-02-03', strategy: 100, benchmark: 100 }, { date: '2020-03-02', strategy: 110, benchmark: 103 }, { date: '2021-02-01', strategy: 112, benchmark: 108 }],
      holdings: [{ decision_date: '2020-01-31', execution_date: '2020-02-03', end_date: '2020-03-02', weights: mode === 'longonly3' ? { XLK: 1, XLF: .65, XLE: .45 } : mode === 'ranked3' ? { XLK: .5, XLF: .25, XLE: .25, XLU: -.5, XLRE: -.25, XLV: -.25 } : { XLK: 2, XLU: -2 }, turnover: 4, trading_cost: .004, funding_cost: .001, borrow_cost: .001, period_return: .1 }],
      diagnostics: { convention: 'Test fixture only' }, assumptions: ['Synthetic test fixture. Never published as production data.'],
    };
    results[mode].holdings[0].scores = [{ symbol: 'XLK', score: 72.5 }, { symbol: 'XLU', score: 28.25 }];
    results[mode].holdings[0].state = { rates: -.25, curve: .5, inflation: .1, vol: -.2, credit: .15 };
  }
  return { ok: true, dataset_id: datasetId, model_version: 'test-model-v5', params, period: { requested_start: params.start, requested_end: params.end, warmup_start: '2018-12-31', first_decision: '2020-01-31', first_execution: '2020-02-03', first_return: '2020-03-02', last_complete_return: '2021-02-01', excluded_partial: true, complete_periods: 12 }, results };
}

async function mockMarket(page, fixture = marketFixture()) {
  await page.route('**/api/market', (route) => route.fulfill({ json: fixture }));
}

async function run(page) {
  await page.getByRole('button', { name: 'Run research' }).click();
  await expect(page.locator('#run-status')).toHaveAttribute('data-phase', 'success');
}

test('repeated runs replace every result and preserve zero-cost assumptions', async ({ page }) => {
  await mockMarket(page);
  const errors = [];
  page.on('pageerror', (error) => errors.push(error.message));
  const urls = [];
  await page.route('**/api/backtest?**', (route) => {
    urls.push(route.request().url());
    return route.fulfill({ json: runFixture(route.request().url(), `test-run-${urls.length}`, urls.length === 1 ? .064 : .091) });
  });
  await page.goto('/');
  await run(page);
  await expect(page.locator('[data-metric="cagr"] .value')).toHaveText('6.40%');
  await expect(page.locator('[data-metric="hit_rate"] .label')).toHaveText('Periods outperforming SPY');
  await expect(page.locator('[data-metric="hit_rate"] .value')).toHaveText('60.00%');
  await page.getByText('Decision scores and macro states', { exact: true }).click();
  await expect(page.locator('#run-results')).toContainText('XLK: 72.50 · XLU: 28.25');
  await expect(page.locator('#run-results svg')).toHaveCount(1);
  await run(page);
  await expect(page.locator('[data-metric="cagr"] .value')).toHaveText('9.10%');
  await expect(page.locator('#run-results svg')).toHaveCount(1);
  await expect(page.locator('#run-results')).not.toContainText('test-run-1');
  await page.locator('#cost-bps').fill('0');
  await page.locator('#borrow-bps').fill('0');
  await expect(page.locator('#run-results')).toBeEmpty();
  await run(page);
  expect(new URL(urls.at(-1)).searchParams.get('cost_bps')).toBe('0');
  expect(new URL(urls.at(-1)).searchParams.get('short_borrow_bps')).toBe('0');
  expect(new URL(urls.at(-1)).searchParams.has('topN')).toBe(false);
  await expect(page.locator('.run-provenance')).toContainText('Trading: 0.0 bps');
  await page.getByText('Executed holdings · 1 periods', { exact: true }).click();
  await expect(page.locator('#run-results')).toContainText('XLK +200.00%');
  expect(errors).toEqual([]);
});

test('a failed rerun clears previous metrics, plots, holdings and provenance', async ({ page }) => {
  await mockMarket(page);
  let calls = 0;
  await page.route('**/api/backtest?**', (route) => {
    calls += 1;
    return calls === 1 ? route.fulfill({ json: runFixture(route.request().url()) }) : route.fulfill({ status: 503, json: { ok: false, error: { code: 'dataset_unavailable', message: 'History is unavailable.' }, request_id: 'test-error-id' } });
  });
  await page.goto('/');
  await run(page);
  await page.getByRole('button', { name: 'Run research' }).click();
  await expect(page.locator('#run-status')).toHaveAttribute('data-phase', 'error');
  await expect(page.locator('#run-error')).toContainText('History is unavailable.');
  await expect(page.locator('#run-error')).toContainText('test-error-id');
  await expect(page.locator('#run-results')).toBeEmpty();
  await expect(page.locator('#backtest-fields')).toBeEnabled();
});

test('compare requests all strategies once and renders each declared identity', async ({ page }) => {
  await mockMarket(page);
  const requests = [];
  await page.route('**/api/backtest?**', (route) => {
    requests.push(route.request().url());
    return route.fulfill({ json: runFixture(route.request().url()) });
  });
  await page.goto('/');
  await page.locator('#mode').selectOption('compare');
  await run(page);
  expect(requests).toHaveLength(1);
  expect(new URL(requests[0]).searchParams.get('mode')).toBe('compare');
  for (const mode of modes) await expect(page.locator(`.strategy-result[data-strategy="${mode}"]`)).toHaveCount(1);
  await expect(page.locator('#run-results svg')).toHaveCount(4);
  await expect(page.locator('.run-provenance')).toContainText('first execution 2020-02-03');
  await expect(page.locator('.run-provenance')).toContainText('test-model-v5');
});

test('mismatched parameters and incorrectly labelled modes cannot publish results', async ({ page }) => {
  await mockMarket(page);
  let calls = 0;
  await page.route('**/api/backtest?**', (route) => {
    const fixture = runFixture(route.request().url());
    calls += 1;
    if (calls === 1) fixture.params.cost_bps = 99;
    else fixture.results.extreme1.strategy.id = 'ranked3';
    return route.fulfill({ json: fixture });
  });
  await page.goto('/');
  for (let index = 0; index < 2; index += 1) {
    await page.getByRole('button', { name: 'Run research' }).click();
    await expect(page.locator('#run-status')).toHaveAttribute('data-phase', 'error');
    await expect(page.locator('#run-results')).toBeEmpty();
  }
});

test('controls lock during a request and a superseded completion cannot overwrite a newer run', async ({ page }) => {
  await mockMarket(page);
  // Prove the identity guard even if an intermediary completes after cancellation.
  await page.addInitScript(() => {
    const nativeFetch = window.fetch.bind(window);
    window.fetch = (input, options) => {
      if (String(input).startsWith('/api/backtest')) {
        const { signal, ...uncancellable } = options || {};
        return nativeFetch(input, uncancellable);
      }
      return nativeFetch(input, options);
    };
  });
  let releaseFirst;
  let firstStarted;
  const started = new Promise((resolve) => { firstStarted = resolve; });
  let requests = 0;
  await page.route('**/api/backtest?**', async (route) => {
    requests += 1;
    if (requests === 1) {
      firstStarted();
      await new Promise((resolve) => { releaseFirst = resolve; });
      await route.fulfill({ json: runFixture(route.request().url(), 'obsolete-run') }).catch(() => {});
    } else await route.fulfill({ json: runFixture(route.request().url(), 'current-run') });
  });
  await page.goto('/');
  await page.getByRole('button', { name: 'Run research' }).click();
  await started;
  await expect(page.locator('#mode')).toBeDisabled();
  await expect(page.locator('#run-backtest')).toBeDisabled();
  // A programmatic change simulates a late navigation/state event while the network is pending.
  await page.locator('#mode').evaluate((node) => { node.value = 'longonly3'; node.dispatchEvent(new Event('change', { bubbles: true })); });
  await run(page);
  const oldCompletion = page.waitForResponse((response) => response.url().includes('/api/backtest?') && response.url().includes('mode=extreme1'));
  releaseFirst();
  await (await oldCompletion).finished();
  await page.evaluate(() => new Promise((resolve) => requestAnimationFrame(resolve)));
  await expect(page.locator('.run-provenance')).toContainText('current-run');
  await expect(page.locator('#run-results')).not.toContainText('obsolete-run');
  await expect(page.locator('.strategy-result')).toHaveAttribute('data-strategy', 'longonly3');
});

test('missing metrics stay unavailable and provider strings remain inert text', async ({ page }) => {
  const payload = '<img src=x onerror="window.injected=true">';
  const market = marketFixture();
  market.assets[0].label = payload;
  market.assets[0].latest = null;
  market.risk_bias.factors.push({ id: 'SPY', label: '20-session equity trend', value: .024, unit: 'fraction', source: 'Test total returns', as_of: '2026-10-16', status: 'ready' });
  await mockMarket(page, market);
  await page.route('**/api/backtest?**', (route) => {
    const fixture = runFixture(route.request().url());
    fixture.results.extreme1.stats.sharpe = null;
    fixture.results.extreme1.equity_curve.forEach((row) => { row.strategy = 100; row.benchmark = 100; });
    fixture.results.extreme1.stats.metric_status.sharpe = 'zero_excess_variance';
    fixture.results.extreme1.assumptions = [payload];
    return route.fulfill({ json: fixture });
  });
  await page.goto('/');
  await expect(page.locator('#assets-table')).toContainText(payload);
  await expect(page.locator('#assets-table')).toContainText('Unavailable');
  await expect(page.locator('#risk-bias')).toContainText('Model review required');
  await expect(page.locator('#risk-bias')).not.toContainText('50');
  await expect(page.locator('#risk-factors')).toContainText('19.35');
  await expect(page.locator('#risk-factors')).toContainText('2.40%');
  await run(page);
  await expect(page.locator('[data-metric="sharpe"] .value')).toHaveText('Unavailable');
  await expect(page.locator('[data-metric="sharpe"] .reason')).toHaveText('zero_excess_variance');
  const axisTicks = await page.locator('#run-results .chart-axis-label').allTextContents();
  expect(axisTicks.some((value) => Number(value) === 100)).toBe(true);
  await expect(page.locator('#run-results .chart-readout-values')).toContainText('100.00');
  await expect(page.locator('.bias-card .tag')).toHaveText('RESEARCH SIGNAL');
  expect(await page.evaluate(() => window.injected)).toBeUndefined();
  await expect(page.locator('img')).toHaveCount(0);
});

test('market source failure removes previously published observations', async ({ page }) => {
  let calls = 0;
  await page.route('**/api/market', (route) => {
    calls += 1;
    return calls === 1 ? route.fulfill({ status: 503, json: marketFixture({ ok: false, status: 'stale' }) }) : route.fulfill({ status: 503, json: { ok: false, error: { code: 'source_failed', message: 'Dataset could not be loaded.' } } });
  });
  await page.goto('/');
  await expect(page.locator('#market-status')).toHaveAttribute('data-status', 'stale');
  await expect(page.locator('#assets-table')).toContainText('620.25');
  await page.getByRole('button', { name: 'Refresh evidence' }).click();
  await expect(page.locator('#market-error')).toBeVisible();
  await expect(page.locator('#assets-table')).not.toContainText('620.25');
  await expect(page.locator('#market-status')).toHaveAttribute('data-status', 'unavailable');
});

test('file mode explains the server requirement without making API requests', async ({ page }) => {
  const requests = [];
  page.on('request', (request) => { if (request.url().includes('/api/')) requests.push(request.url()); });
  await page.goto(pathToFileURL(path.resolve('index.html')).href);
  await expect(page.locator('#file-notice')).toBeVisible();
  await expect(page.locator('#file-notice')).toContainText('uv run uvicorn app:app --reload');
  await expect(page.locator('#run-backtest')).toBeDisabled();
  await expect(page.locator('#refresh-market')).toBeDisabled();
  expect(requests).toEqual([]);
});

test('mobile navigation and results remain within the viewport', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await mockMarket(page);
  await page.route('**/api/backtest?**', (route) => route.fulfill({ json: runFixture(route.request().url()) }));
  await page.goto('/');
  await run(page);
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
  await expect(page.getByRole('navigation', { name: 'Main navigation' })).toBeVisible();
  await expect(page.locator('#run-results svg')).toHaveCount(1);
});

function analyticsFixture() {
  const sections = {};
  for (const key of ['risk', 'changes', 'anomalies', 'correlations', 'rates', 'volatility', 'fx', 'sectors', 'playbook', 'analogues']) {
    sections[key] = {
      title: `${key} analysis`, status: 'ready', summary: `Computed ${key} summary from dated inputs.`,
      metrics: [{ label: 'Observed value', value: 5, unit: 'percent' }, { label: 'Classification', value: 'Constructive', unit: 'text' }],
      charts: [{ title: `${key} curve`, unit: 'percent', series: [{ label: 'Observed', points: [{ date: '2Y', value: 4.25 }, { date: '10Y', value: 4.5 }] }] }],
      tables: [{ title: `${key} details`, columns: ['Observation', 'Value'], rows: [['Measured', .25], ['Missing', null]] }],
    };
  }
  return { ok: true, status: 'ready', dataset_id: `sha256:${'b'.repeat(64)}`, as_of: '2026-10-16', model_version: 'test-analytics', source: mockSource, sections };
}

test('all analytical families render calculations, categorical charts and explicit mock provenance', async ({ page }) => {
  await mockMarket(page, marketFixture({ source: mockSource }));
  const analytics = analyticsFixture();
  analytics.sections.risk.metrics = [{ label: '1D risk score', value: 25, unit: 'score' }, { label: '1W risk score', value: -15, unit: 'score' }, { label: '1M risk score', value: 10, unit: 'score' }];
  await page.route('**/api/analytics', (route) => route.fulfill({ json: analytics }));
  await page.goto('/');
  await expect(page.locator('#mock-notice')).toBeVisible();
  await expect(page.locator('#source-indicator')).toContainText('MOCK DATA');
  await expect(page.locator('#mock-description')).toContainText('Seed 8042');
  await expect(page.locator('[data-analysis]')).toHaveCount(10);
  await expect(page.locator('[data-analysis="rates"]')).toContainText('5.00%');
  await expect(page.locator('[data-analysis="rates"]')).not.toContainText('500.00%');
  await expect(page.locator('#risk-factors')).toContainText('-15.00');
  await page.locator('[data-analysis="rates"] summary').click();
  await expect(page.locator('[data-analysis="rates"] svg')).toBeVisible();
  await expect(page.locator('[data-analysis="rates"] svg')).toContainText('2Y');
  await expect(page.locator('[data-analysis="rates"] .chart-observation')).toHaveCount(2);
  await expect(page.locator('[data-analysis="rates"] table')).toContainText('—');
  const downloadPromise = page.waitForEvent('download');
  await page.getByRole('button', { name: 'Download all analytics' }).click();
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toBe('radar-analytics-2026-10-16.json');
  const stream = await download.createReadStream();
  let content = '';
  for await (const chunk of stream) content += chunk;
  expect(JSON.parse(content).source).toEqual(mockSource);
});

test('mismatched analytical snapshots are withheld without discarding valid market observations', async ({ page }) => {
  await mockMarket(page);
  let calls = 0;
  await page.route('**/api/analytics', (route) => {
    const fixture = signalFixture();
    if (++calls > 1) fixture.dataset_id = 'different-dataset';
    return route.fulfill({ json: fixture });
  });
  await page.goto('/');
  await expect(page.locator('#signal-board .signal-card')).toHaveCount(4);
  await expect(page.locator('#risk-factors .horizon-item')).toHaveCount(3);
  await page.getByRole('button', { name: 'Refresh evidence' }).click();
  await expect(page.locator('#analytics-error')).toContainText('did not match');
  await expect(page.locator('#assets-table')).toContainText('620.25');
  await expect(page.locator('[data-analysis]')).toHaveCount(0);
  await expect(page.locator('#signal-board .signal-card')).toHaveCount(0);
  await expect(page.locator('#risk-factors .horizon-item')).toHaveCount(0);
});

function signalFixture(severity = 'HIGH') {
  const fixture = analyticsFixture();
  fixture.sections.risk.summary = '1D: Neutral; 1W: Bearish; 1M: Bullish. MID horizon divergence. Strength is not a forecast probability.';
  fixture.sections.risk.metrics = [
    { label: '1D risk score', value: 10, unit: 'score' },
    { label: '1W risk score', value: -30, unit: 'score' },
    { label: '1M risk score', value: 40, unit: 'score' },
    { label: 'Horizon divergence', value: 'MID', unit: 'text' },
    { label: 'Horizon alignment', value: 'Conflicting horizon directions', unit: 'text' },
  ];
  const elevated = severity === 'HIGH';
  fixture.sections.anomalies.metrics = [{ label: 'Elevated anomalies', value: elevated ? 2 : 0, unit: 'count' }];
  fixture.sections.anomalies.tables = [{
    title: 'Anomalies ranked by magnitude', columns: ['Series', 'Signed z', 'Percentile (%)', 'Severity', '1D change', 'Unit'],
    rows: [['SPY', elevated ? 3.1 : 1.2, 97, severity, 1.2, '%'], ['TLT', elevated ? -4.1 : -1.8, 3, severity, -.5, '%']],
  }];
  fixture.sections.volatility.metrics = [
    { label: 'Volatility regime', value: 'NORMAL', unit: 'text' },
    { label: 'VIX implied volatility', value: 19.2, unit: 'percent' },
    { label: 'IV−RV20 premium', value: 5, unit: 'percentage_points' },
  ];
  fixture.sections.sectors.metrics = [{ label: 'Top sector', value: 'XLU', unit: 'text' }, { label: 'Bottom sector', value: 'XLK', unit: 'text' }];
  return fixture;
}

test('signal focus follows published direction and outlier severity rather than raw sign or rank', async ({ page }) => {
  await mockMarket(page);
  await page.route('**/api/analytics', (route) => route.fulfill({ json: signalFixture() }));
  await page.goto('/');
  await expect(page.locator('.risk-headline')).toHaveText('Short-term neutral');
  await expect(page.locator('.horizon-direction')).toHaveText(['Neutral', 'Bearish', 'Bullish']);
  await expect(page.locator('.horizon-value')).toHaveText(['+10.00', '-30.00', '+40.00']);
  await expect(page.locator('.horizon-item').nth(0)).not.toHaveAttribute('data-tone', 'positive');
  const shock = page.locator('#signal-board a[href="#analysis-anomalies"]');
  await expect(shock).toContainText('TLT -4.10σ');
  await expect(shock).toContainText('HIGH · 2 elevated outliers');
  await expect(shock).toHaveAttribute('data-tone', 'negative');
  await expect(page.locator('#analysis-anomalies .signal-preview tbody tr').first()).toHaveAttribute('data-signal', 'high');
  await expect(page.locator('#signal-board a[href="#analysis-volatility"]')).toContainText('VIX 19.2% · IV−RV +5.0 pp');
  for (const link of await page.locator('#signal-board a').all()) {
    const target = await link.getAttribute('href');
    await expect(page.locator(target)).toHaveCount(1);
  }
});

test('ordinary largest moves remain ordinary and unavailable reloads remove previous signal claims', async ({ page }) => {
  await mockMarket(page);
  let calls = 0;
  await page.route('**/api/analytics', (route) => {
    const fixture = signalFixture('ORDINARY');
    if (++calls > 1) {
      Object.values(fixture.sections).forEach((section) => { section.status = 'unavailable'; section.metrics = []; section.tables = []; section.charts = []; });
    }
    return route.fulfill({ json: fixture });
  });
  await page.goto('/');
  const shock = page.locator('#signal-board a[href="#analysis-anomalies"]');
  await expect(shock).toContainText('TLT -1.80σ');
  await expect(shock).toContainText('ORDINARY · 0 elevated outliers');
  await expect(shock).not.toHaveAttribute('data-tone', /negative|warning/);
  await expect(page.locator('#analysis-anomalies tr[data-signal]')).toHaveCount(0);
  await page.getByRole('button', { name: 'Refresh evidence' }).click();
  await expect(shock).toHaveAttribute('data-tone', 'neutral');
  await expect(shock.locator('.signal-value')).toHaveText('Unavailable');
  await expect(page.locator('#signal-board')).not.toContainText('TLT -1.80σ');
  await expect(page.locator('#risk-factors .horizon-item')).toHaveCount(0);
});

test('charts expose actual observations by keyboard and pointer and preserve missing-value gaps', async ({ page }) => {
  await mockMarket(page);
  const fixture = analyticsFixture();
  fixture.sections.rates.charts = [{ title: 'Treasury curve snapshots', unit: 'percent', series: [
    { label: 'Today', points: [{ date: '2Y', value: 4.25 }, { date: '5Y', value: null }, { date: '10Y', value: 4.5 }] },
    { label: 'Prior session', points: [{ date: '2Y', value: 4 }, { date: '5Y', value: 4.1 }, { date: '10Y', value: 4.4 }] },
  ] }];
  await page.route('**/api/analytics', (route) => route.fulfill({ json: fixture }));
  await page.goto('/');
  const chart = page.locator('#analysis-rates .signal-chart').first();
  const plot = chart.locator('.signal-chart-plot');
  await expect(chart.locator('.chart-readout-date')).toHaveText('10Y');
  await plot.focus();
  await plot.press('Home');
  await expect(chart.locator('.chart-readout-date')).toHaveText('2Y');
  await expect(chart.locator('.chart-readout-item strong')).toHaveText(['4.25%', '4.00%']);
  await plot.press('ArrowRight');
  await expect(chart.locator('.chart-readout-date')).toHaveText('5Y');
  await expect(chart.locator('.chart-readout-item strong')).toHaveText(['—', '4.10%']);
  const path = await chart.locator('.chart-series[data-series="0"]').getAttribute('d');
  expect(path.match(/M/g)).toHaveLength(2);
  expect(path).not.toContain('L');
  await plot.press('End');
  await expect(chart.locator('.chart-readout-item strong')).toHaveText(['4.50%', '4.40%']);
  const legend = chart.getByRole('button', { name: /Prior session/ });
  await legend.click();
  await expect(legend).toHaveAttribute('aria-pressed', 'true');
  await expect(chart.locator('.chart-series[data-series="1"]')).toHaveClass(/is-focused/);
  const box = await plot.boundingBox();
  await page.mouse.move(box.x + 1, box.y + box.height / 2);
  await expect(chart.locator('.chart-readout-date')).toHaveText('2Y');
});

test('frequency and basket controls publish full annual, benchmark and attribution research', async ({ page }) => {
  await mockMarket(page);
  const requests = [];
  await page.route('**/api/backtest?**', (route) => {
    requests.push(route.request().url());
    const fixture = runFixture(route.request().url());
    fixture.source = mockSource;
    for (const result of Object.values(fixture.results)) {
      result.benchmark_stats = { ...result.stats, cagr: .04 };
      result.annual_returns = [{ year: 2020, strategy: .08, benchmark: .05, excess: .03, partial: true, start: '2020-02-03', end: '2020-12-31' }];
      result.drawdown_curve = [{ date: '2020-02-03', strategy: 0, benchmark: 0 }, { date: '2020-03-02', strategy: -.04, benchmark: -.02 }];
      result.rolling_excess = [{ date: '2021-02-01', value: .03 }];
      result.diagnostics = { rank_persistence: .7, top_retention: .6, average_holding_days: 40, top_beats_bottom_rate: .65, positive_net_spread_rate: .55, average_top_return: .024, average_bottom_return: -.006, average_top_bottom_spread: .03, attribution: [{ symbol: 'XLK', long_contribution: .03, short_contribution: -.01, total_contribution: .02 }], score_attribution: [{ factor: 'rates', average_long_score_points: 3, average_short_score_points: -2 }], regime_performance: [{ regime: 'Constructive', periods: 12, hit_rate: .6, average_return: .01, average_excess: .005 }] };
    }
    return route.fulfill({ json: fixture });
  });
  await page.goto('/');
  await expect(page.locator('#top-n')).toBeDisabled();
  await page.locator('#mode').selectOption('ranked3');
  await expect(page.locator('#top-n')).toBeEnabled();
  await page.locator('#top-n').selectOption('5');
  await page.locator('#rebalance').selectOption('weekly');
  await run(page);
  expect(new URL(requests[0]).searchParams.get('top_n')).toBe('5');
  expect(new URL(requests[0]).searchParams.get('rebalance')).toBe('weekly');
  await expect(page.locator('.run-provenance')).toContainText('MOCK DATA');
  await expect(page.locator('#run-results')).toContainText('Annual returns & excess performance');
  await expect(page.locator('#run-results')).toContainText('partial year');
  await expect(page.locator('#run-results svg')).toHaveCount(4);
  await page.getByText('Ranking stability & rotation diagnostics', { exact: true }).click();
  await expect(page.locator('#run-results')).toContainText('65.00%');
  const ranking = page.locator('details').filter({ has: page.getByText('Ranking stability & rotation diagnostics', { exact: true }) });
  await expect(ranking.locator('.metric').filter({ hasText: 'Top-ranked sector · average return per cycle' }).locator('.value')).toHaveText('2.40%');
  await expect(ranking.locator('.metric').filter({ hasText: 'Bottom-ranked sector · average return per cycle' }).locator('.value')).toHaveText('-0.60%');
  await expect(ranking.locator('.metric').filter({ hasText: 'Top minus bottom · average spread per cycle' }).locator('.value')).toHaveText('3.00%');
  await expect(ranking).not.toContainText('monthly');
  await page.getByText('Factor score attribution', { exact: true }).click();
  await expect(page.locator('#run-results')).toContainText('not realized investment returns');
  await page.locator('#rebalance').selectOption('quarterly');
  await expect(page.locator('#run-results')).toBeEmpty();
});

test('studies use matched assumptions, lock controls and clear errors on invalidation', async ({ page }) => {
  await mockMarket(page);
  let calls = 0;
  let release;
  await page.route('**/api/studies?**', async (route) => {
    calls += 1;
    if (calls > 1) return route.fulfill({ status: 429, json: { ok: false, error: { message: 'Calculation capacity is busy.', code: 'busy' } } });
    await new Promise((resolve) => { release = resolve; });
    const base = runFixture(route.request().url());
    return route.fulfill({ json: { ok: true, source: mockSource, dataset_id: base.dataset_id, model_version: base.model_version, params: base.params, robustness: [{ top_n: 3, rebalance: 'monthly', stats: base.results.extreme1.stats }], cost_sensitivity: [{ cost_bps: 0, stats: base.results.extreme1.stats }], regime_performance: [], methodology: ['Point-in-time decisions; matching dataset.'] } });
  });
  await page.goto('/');
  await page.getByRole('button', { name: 'Run studies' }).click();
  await expect(page.locator('#study-status')).toContainText('Calculating');
  await expect(page.locator('#mode')).toBeDisabled();
  await expect(page.locator('#run-backtest')).toBeDisabled();
  await expect.poll(() => Boolean(release)).toBe(true);
  release();
  await expect(page.locator('#study-status')).toContainText('Studies complete');
  await expect(page.locator('#study-results')).toContainText('MOCK DATA');
  await expect(page.locator('#study-results')).toContainText('0.0 bps');
  await page.getByRole('button', { name: 'Run studies' }).click();
  await expect(page.locator('#study-error')).toContainText('Calculation capacity is busy');
  await expect(page.locator('#study-results')).toBeEmpty();
  await page.locator('#cost-bps').fill('0');
  await expect(page.locator('#study-error')).toBeHidden();
  await expect(page.locator('#study-results')).toBeEmpty();
});

test('a superseded study cannot publish after a parameter change', async ({ page }) => {
  await mockMarket(page);
  await page.addInitScript(() => {
    const nativeFetch = window.fetch.bind(window);
    window.fetch = (input, options) => {
      if (String(input).startsWith('/api/studies')) {
        const { signal, ...uncancellable } = options || {};
        return nativeFetch(input, uncancellable);
      }
      return nativeFetch(input, options);
    };
  });
  let release;
  await page.route('**/api/studies?**', async (route) => {
    await new Promise((resolve) => { release = resolve; });
    const base = runFixture(route.request().url(), 'obsolete-study');
    return route.fulfill({ json: { ok: true, source: mockSource, dataset_id: base.dataset_id, model_version: base.model_version, params: base.params, robustness: [], cost_sensitivity: [] } });
  });
  await page.goto('/');
  await page.locator('#run-studies').click();
  await expect.poll(() => Boolean(release)).toBe(true);
  await page.locator('#rebalance').evaluate((node) => { node.value = 'quarterly'; node.dispatchEvent(new Event('change', { bubbles: true })); });
  const completion = page.waitForResponse((response) => response.url().includes('/api/studies?'));
  release();
  await (await completion).finished();
  await page.evaluate(() => new Promise((resolve) => requestAnimationFrame(resolve)));
  await expect(page.locator('#study-results')).toBeEmpty();
  await expect(page.locator('#study-status')).toContainText('Parameters changed');
  await expect(page.locator('#run-studies')).toBeEnabled();
});
