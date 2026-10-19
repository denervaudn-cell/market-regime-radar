/* Presentation only. All financial calculations belong to the Python API. */
(() => {
  'use strict';

  const $ = (id) => document.getElementById(id);
  const finite = (value) => typeof value === 'number' && Number.isFinite(value);
  const number = (value, digits = 2) => finite(value)
    ? value.toLocaleString('en-US', { minimumFractionDigits: digits, maximumFractionDigits: digits })
    : 'Unavailable';
  const percent = (value, signed = false) => finite(value)
    ? `${signed && value > 0 ? '+' : ''}${number(value * 100)}%` : 'Unavailable';
  const date = (value) => typeof value === 'string' && /^\d{4}-\d{2}-\d{2}/.test(value)
    ? value.slice(0, 10) : 'Unavailable';
  const list = (value) => Array.isArray(value) ? value : [];
  const text = (value, fallback = 'Unavailable') => typeof value === 'string' && value.length ? value : fallback;
  const freeze = (value) => {
    if (value && typeof value === 'object' && !Object.isFrozen(value)) {
      Object.values(value).forEach(freeze);
      Object.freeze(value);
    }
    return value;
  };
  const element = (tag, className, value) => {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (value !== undefined) node.textContent = value;
    return node;
  };
  const fragment = (...children) => {
    const result = document.createDocumentFragment();
    result.append(...children);
    return result;
  };
  const badge = (status, label = status) => {
    const node = element('span', 'badge', text(label));
    node.dataset.status = ['ready', 'success', 'stale', 'unavailable', 'partial', 'error'].includes(status) ? status : 'unavailable';
    return node;
  };
  const tone = (value) => finite(value) ? value > 0 ? 'positive' : value < 0 ? 'negative' : '' : 'muted';
  const unavailable = (message) => element('p', 'empty-state', message);
  const strategyLabels = {
    extreme1: 'Extreme conviction', ranked3: 'Ranked three', longonly3: 'Leveraged long only',
  };
  const descriptions = {
    extreme1: 'Highest-ranked sector +200%; lowest-ranked sector −200%. Gross exposure 400%.',
    ranked3: 'Three longs and three shorts at 50/25/25 within each 100% leg. The worst-ranked sector receives the largest short weight.',
    longonly3: 'Top three sectors at +100%, +65% and +45%. Total long exposure 210%; excess exposure is financed.',
    compare: 'Run all three strategies on the same dataset, dates and cost assumptions. SPY is the common benchmark.',
  };
  let state = freeze({ market: { phase: 'idle' }, run: { phase: 'idle', params: null, result: null } });
  let marketSequence = 0;
  let runSequence = 0;
  let marketController;
  let runController;
  const fileMode = location.protocol === 'file:';

  function setState(key, next) {
    state = freeze({ ...state, [key]: next });
  }

  function table(headers, rows, caption) {
    const wrapper = element('div', 'table-wrap');
    const node = element('table', 'data-table');
    const head = element('thead');
    const headerRow = element('tr');
    headers.forEach((label) => {
      const cell = element('th', '', label);
      cell.scope = 'col';
      headerRow.append(cell);
    });
    head.append(headerRow);
    const body = element('tbody');
    rows.forEach((values) => {
      const row = element('tr');
      values.forEach((value) => {
        const cell = element('td');
        if (value instanceof Node) cell.append(value);
        else cell.textContent = value ?? 'Unavailable';
        row.append(cell);
      });
      body.append(row);
    });
    node.append(head, body);
    if (caption) node.append(element('caption', '', caption));
    wrapper.append(node);
    return wrapper;
  }

  function chart(series, title, valueLabel = 'NAV') {
    const valid = series.filter((item) => item.points.length > 0);
    const points = valid.flatMap((item) => item.points).filter((item) => finite(item.value) && finite(Date.parse(item.date)));
    if (!points.length) return unavailable('No chart observations available.');
    const ns = 'http://www.w3.org/2000/svg';
    const svgElement = (tag, attrs = {}, content) => {
      const node = document.createElementNS(ns, tag);
      Object.entries(attrs).forEach(([key, value]) => node.setAttribute(key, value));
      if (content !== undefined) node.textContent = content;
      return node;
    };
    const width = 820, height = 280, left = 58, right = 18, top = 22, bottom = 36;
    const times = points.map((item) => Date.parse(item.date));
    const values = points.map((item) => item.value);
    const minTime = Math.min(...times), maxTime = Math.max(...times);
    const minimum = Math.min(...values), maximum = Math.max(...values);
    const margin = Math.max((maximum - minimum) * .1, Math.abs(maximum) * .015, .01);
    const low = minimum - margin, high = maximum + margin;
    const tickDigits = high - low < 10 ? 2 : high - low < 100 ? 1 : 0;
    const x = (value) => left + (Date.parse(value) - minTime) / (maxTime - minTime || 1) * (width - left - right);
    const y = (value) => top + (high - value) / (high - low) * (height - top - bottom);
    const svg = svgElement('svg', { viewBox: `0 0 ${width} ${height}`, class: 'chart', role: 'img', 'aria-label': title });
    svg.append(svgElement('title', {}, title));
    svg.append(svgElement('desc', {}, `${valueLabel}. ${date(new Date(minTime).toISOString())} to ${date(new Date(maxTime).toISOString())}. Detailed values follow the chart.`));
    for (let i = 0; i <= 4; i += 1) {
      const value = low + (high - low) * i / 4;
      svg.append(svgElement('line', { x1: left, x2: width - right, y1: y(value), y2: y(value), class: 'axis' }));
      svg.append(svgElement('text', { x: left - 10, y: y(value) + 4, 'text-anchor': 'end' }, number(value, tickDigits)));
    }
    const endpointDates = [new Date(minTime).toISOString(), new Date(maxTime).toISOString()];
    endpointDates.forEach((value, index) => svg.append(svgElement('text', {
      x: index === 0 ? left : width - right, y: height - 8, 'text-anchor': index === 0 ? 'start' : 'end',
    }, date(value))));
    valid.forEach((item) => {
      // A missing observation breaks a path; it is never converted into a zero.
      let drawing = false;
      const path = item.points.map((point) => {
        if (!finite(point.value) || !finite(Date.parse(point.date))) { drawing = false; return ''; }
        const command = drawing ? 'L' : 'M';
        drawing = true;
        return `${command}${x(point.date).toFixed(2)},${y(point.value).toFixed(2)}`;
      }).join(' ');
      svg.append(svgElement('path', { d: path, fill: 'none', stroke: item.color, 'stroke-width': 2, 'vector-effect': 'non-scaling-stroke' }));
    });
    const wrapper = element('div', 'chart-wrap');
    wrapper.append(svg);
    const legend = element('div', 'chart-legend');
    valid.forEach((item) => {
      const label = element('span', 'legend-item');
      const line = element('span', 'legend-line');
      line.classList.add({ '#7de0c5': 'mint', '#91b5ff': 'blue', '#e8ba83': 'amber', '#9ca8b9': 'gray' }[item.color] || 'gray');
      label.append(line, document.createTextNode(item.label));
      legend.append(label);
    });
    return fragment(wrapper, legend);
  }

  async function request(path, controller, allowDegradedMarket = false) {
    const timeout = setTimeout(() => controller.abort('timeout'), 60000);
    try {
      const response = await fetch(path, { signal: controller.signal, headers: { Accept: 'application/json' } });
      let payload;
      try { payload = await response.json(); }
      catch { throw new Error('The API returned an unreadable response. Check the server and try again.'); }
      const degradedMarket = allowDegradedMarket && response.status === 503 && ['stale', 'unavailable'].includes(payload?.status) && Array.isArray(payload?.assets) && Array.isArray(payload?.rates) && typeof payload?.dataset_id === 'string';
      if ((!response.ok || payload?.ok !== true) && !degradedMarket) {
        const message = text(payload?.error?.message, `The request failed (HTTP ${response.status}).`);
        const code = typeof payload?.error?.code === 'string' ? ` [${payload.error.code}]` : '';
        const identity = typeof payload?.request_id === 'string' ? ` · Request ${payload.request_id}` : '';
        throw new Error(`${message}${code}${identity}`);
      }
      return payload;
    } catch (error) {
      if (controller.signal.reason === 'timeout') throw new Error('The request timed out. No result was published. Try again after checking the data service.');
      throw error;
    } finally { clearTimeout(timeout); }
  }

  function renderRisk(data) {
    const bias = data.risk_bias || {};
    const factors = element('div', 'factor-list');
    list(bias.factors).forEach((factor) => {
      const item = element('div', 'factor');
      const value = factor.unit ? panelValue(factor) : number(factor.value);
      const contribution = finite(factor.contribution) ? ` · contribution ${number(factor.contribution)}` : '';
      item.append(element('p', 'factor-label', text(factor.label)), element('div', 'factor-value', value), element('div', 'factor-source', `${text(factor.source)} · ${date(factor.as_of)}${contribution}`));
      factors.append(item);
    });
    if (!factors.childElementCount) factors.append(unavailable('No risk observations are available.'));
    if (bias.status !== 'ready' || !finite(bias.score)) {
      return { bias: fragment(element('p', 'unavailable', text(bias.label, 'Unavailable')), element('p', 'bias-explanation', text(bias.explanation, 'The composite requires model review. Available inputs are shown separately.'))), factors };
    }
    const label = element('p', 'bias-label', text(bias.label));
    const normalizedLabel = String(bias.label).toLowerCase();
    label.dataset.tone = normalizedLabel.includes('bear') || normalizedLabel.includes('risk_off') ? 'bearish' : normalizedLabel.includes('neutral') ? 'neutral' : 'bullish';
    return { bias: fragment(label, element('p', 'bias-score', `${number(bias.score, 0)} / 100 · heuristic score`), element('p', 'bias-explanation', text(bias.explanation, 'A descriptive signal, not a calibrated probability.'))), factors };
  }

  function renderAssets(assets) {
    if (!assets.length) return unavailable('No ETF observations available.');
    return table(['Asset / proxy', 'Close, USD', '1 day', '20 sessions', '1D z-score', 'Return percentile', 'As of / status'], assets.map((asset) => {
      const name = element('span');
      name.append(element('span', 'asset-symbol', text(asset.symbol)), element('span', 'asset-name', text(asset.label)));
      const status = element('span');
      status.append(element('span', 'asset-name', date(asset.as_of)), badge(asset.status));
      const close = element('span', '', number(asset.latest));
      const dailyChange = element('span', tone(asset.change_1d), percent(asset.change_1d, true));
      const monthlyChange = element('span', tone(asset.change_20d), percent(asset.change_20d, true));
      dailyChange.title = monthlyChange.title = `Return source: ${text(asset.return_source)} · ${text(asset.return_basis)} · ${date(asset.return_as_of)}`;
      close.title = `Source: ${text(asset.source)}`;
      return [name, close, dailyChange, monthlyChange, number(asset.z_1d), finite(asset.percentile) ? `${number(asset.percentile, 0)} / 100` : 'Unavailable', status];
    }), 'Quoted closes and dividend-inclusive returns use separate series. Return percentile ranks the latest daily return against prior observations. ETF proxies are not spot commodities or the underlying indices.');
  }

  function renderRates(rates) {
    if (!rates.length) return unavailable('No Treasury yields available.');
    return table(['Tenor', 'Yield', 'Source', 'As of', 'Status'], rates.map((rate) => [text(rate.tenor), finite(rate.value) ? `${number(rate.value)}%` : 'Unavailable', text(rate.source), date(rate.as_of), badge(rate.status)]));
  }

  function renderCorrelation(correlation) {
    if (!list(correlation?.labels).length) return unavailable('Insufficient overlapping return observations.');
    const labels = correlation.labels;
    const node = table(['', ...labels], labels.map((label, i) => [label, ...labels.map((_, j) => {
      const value = correlation.matrix?.[i]?.[j];
      const samples = correlation.sample_sizes?.[i]?.[j];
      const cell = element('span', '', finite(value) ? number(value) : '—');
      cell.title = `${label} / ${labels[j]}: ${finite(value) ? number(value) : 'Unavailable'}; ${finite(samples) ? samples : 'unknown'} paired observations`;
      cell.setAttribute('aria-label', cell.title);
      if (finite(value)) {
        cell.classList.add('heat-cell', `${value >= 0 ? 'positive' : 'negative'}-${Math.min(4, Math.ceil(Math.abs(value) * 4))}`);
      }
      return cell;
    })]), 'Hover or focus a value’s table cell to inspect the common sample count. — means unavailable.');
    node.querySelector('table').classList.add('heatmap');
    node.querySelectorAll('td span').forEach((cell) => cell.setAttribute('tabindex', '0'));
    return node;
  }

  function panelValue(item) {
    if (!finite(item.value)) return 'Unavailable';
    if (item.unit === 'fraction') return percent(item.value);
    if (item.unit === 'percent' || item.unit === 'percent_annualized') return `${number(item.value)}%`;
    if (item.unit === 'percentage_points') return `${number(item.value)} pp`;
    if (typeof item.unit === 'string' && /^[A-Z]{3}\/[A-Z]{3}$/.test(item.unit)) return `${number(item.value, 4)} ${item.unit}`;
    return number(item.value);
  }

  function renderPanels(panels) {
    const result = document.createDocumentFragment();
    const names = { yield_curve: 'Curve structure', volatility: 'Volatility evidence', fx: 'FX evidence' };
    Object.entries(names).forEach(([key, label]) => {
      const panel = panels?.[key] || { status: 'unavailable', reason: 'Required observations are not supplied.' };
      const card = element('article', 'card');
      const heading = element('div', 'card-heading');
      heading.append(element('h3', '', label), badge(panel.status));
      card.append(heading);
      if (panel.reason) card.append(element('p', 'small muted', panel.reason));
      if (list(panel.items).length) {
        const definitions = element('dl', 'metric-list');
        panel.items.forEach((item) => {
          const row = element('div');
          const value = element('dd', '', panelValue(item));
          value.append(element('small', '', `${text(item.source)} · ${date(item.as_of)} · ${text(item.status)}`));
          row.append(element('dt', '', text(item.label)), value);
          definitions.append(row);
        });
        card.append(definitions);
      } else card.append(unavailable('Unavailable until the required inputs and calculation are supplied.'));
      result.append(card);
    });
    return result;
  }

  function renderCoverage(data) {
    const metadata = data.metadata || {};
    const summary = element('p', 'small muted', `Dataset ${text(data.dataset_id)} · as of ${date(data.as_of)} · generated ${text(data.generated_at)} · expected session ${date(metadata.expected_session)} · calendar ${text(metadata.calendar_status)}.`);
    const series = list(metadata.series);
    return fragment(summary, series.length ? table(['Series', 'Source', 'As of', 'Available at', 'Status', 'Reason'], series.map((item) => [text(item.id), text(item.source), date(item.as_of), text(item.available_at), badge(item.status), text(item.reason, '—')])) : unavailable('Detailed source coverage was not supplied by this dataset.'));
  }

  function clearMarket() {
    $('risk-bias').replaceChildren(element('p', 'unavailable', 'Unavailable'), element('p', 'bias-explanation', 'No current market result is published.'));
    $('risk-factors').replaceChildren(unavailable('Required evidence is unavailable.'));
    $('assets-table').replaceChildren(unavailable('No market observations available.'));
    $('rates-content').replaceChildren(unavailable('No rate observations available.'));
    $('correlation-content').replaceChildren(unavailable('No common history available.'));
    $('derived-panels').replaceChildren(renderPanels(null));
    $('coverage-content').replaceChildren(unavailable('No validated dataset loaded.'));
    $('coverage-status').replaceWith(Object.assign(badge('unavailable'), { id: 'coverage-status' }));
    $('market-provenance').textContent = 'No observations published';
  }

  async function loadMarket() {
    if (fileMode) return;
    const sequence = ++marketSequence;
    marketController?.abort();
    marketController = new AbortController();
    const controller = marketController;
    setState('market', { phase: 'loading' });
    $('refresh-market').disabled = true;
    $('market-status').textContent = 'Loading evidence';
    $('market-status').dataset.status = 'loading';
    $('market-error').hidden = true;
    clearMarket();
    try {
      const data = await request('/api/market', controller, true);
      if (sequence !== marketSequence) return;
      if (!Array.isArray(data.assets) || !Array.isArray(data.rates) || typeof data.dataset_id !== 'string') throw new Error('The market response does not match the supported API contract.');
      const risk = renderRisk(data);
      const updates = {
        'risk-bias': risk.bias, 'risk-factors': risk.factors, 'assets-table': renderAssets(data.assets),
        'rates-content': renderRates(data.rates), 'correlation-content': renderCorrelation(data.correlation),
        'derived-panels': renderPanels(data.panels), 'coverage-content': renderCoverage(data),
      };
      Object.entries(updates).forEach(([id, content]) => $(id).replaceChildren(content));
      $('market-status').replaceWith(Object.assign(badge(data.status, `Market evidence · ${text(data.status)}`), { id: 'market-status' }));
      $('market-status').setAttribute('role', 'status');
      $('coverage-status').replaceWith(Object.assign(badge(data.status), { id: 'coverage-status' }));
      $('market-provenance').textContent = `As of ${date(data.as_of)} · Dataset ${data.dataset_id}`;
      if (data.status !== 'ready') {
        $('market-error').textContent = 'Market coverage is incomplete or stale. Inspect each observation’s status and the dataset coverage below.';
        $('market-error').hidden = false;
      }
      setState('market', { phase: data.status === 'ready' ? 'success' : 'degraded', result: data });
    } catch (error) {
      if (sequence !== marketSequence) return;
      clearMarket();
      setState('market', { phase: 'error', error: error.message });
      $('market-status').textContent = 'Market evidence unavailable';
      $('market-status').dataset.status = 'unavailable';
      $('market-error').textContent = error.message;
      $('market-error').hidden = false;
    } finally {
      if (sequence === marketSequence) $('refresh-market').disabled = false;
    }
  }

  function readParams() {
    return freeze({ start: $('start').value, end: $('end').value || null, mode: $('mode').value, cost_bps: Number($('cost-bps').value), short_borrow_bps: Number($('borrow-bps').value), rebalance: 'monthly' });
  }

  function invalidateRun() {
    runSequence += 1;
    runController?.abort();
    setState('run', { phase: 'idle', params: null, result: null });
    $('backtest-fields').disabled = fileMode;
    $('run-results').replaceChildren();
    $('run-results').setAttribute('aria-busy', 'false');
    $('run-error').hidden = true;
    $('run-status').textContent = 'Parameters changed · run research to calculate a matching result.';
    $('run-status').dataset.phase = 'idle';
    $('strategy-description').textContent = descriptions[$('mode').value] || 'Choose a supported strategy.';
    $('end').setCustomValidity('');
  }

  function validateRun(data, params) {
    if (typeof data.dataset_id !== 'string' || typeof data.model_version !== 'string' || !data.period || !data.results || !data.params) throw new Error('The research response does not match the supported API contract.');
    for (const key of Object.keys(params)) {
      if ((data.params[key] ?? null) !== params[key]) throw new Error('Returned assumptions do not match this request. No result was published.');
    }
    const modes = params.mode === 'compare' ? Object.keys(strategyLabels) : [params.mode];
    if (Object.keys(data.results).sort().join() !== [...modes].sort().join()) throw new Error('The API returned different strategies from the requested mode.');
    for (const mode of modes) {
      const result = data.results[mode];
      if (result?.strategy?.id !== mode || !result.stats || !Array.isArray(result.equity_curve) || !Array.isArray(result.holdings)) throw new Error('The strategy result is incomplete or incorrectly labelled.');
      if (result.equity_curve.some((row) => !finite(row.strategy) || !finite(row.benchmark) || !finite(Date.parse(row.date)))) throw new Error('The equity curve contains invalid observations. No result was published.');
    }
  }

  const metrics = [
    ['cagr', 'Annualized return', percent], ['annualized_volatility', 'Annualized volatility', percent],
    ['sharpe', 'Sharpe · excess returns', number], ['max_drawdown_monthly', 'Monthly drawdown', percent],
    ['total_return', 'Total return', percent], ['benchmark_total_return', 'SPY total return', percent],
    ['hit_rate', 'Periods outperforming SPY', percent], ['annualized_turnover', 'Annual turnover', percent],
  ];

  function renderMetrics(stats) {
    const grid = element('div', 'metrics');
    metrics.forEach(([key, label, formatter]) => {
      const metric = element('div', 'metric');
      metric.dataset.metric = key;
      metric.append(element('div', 'label', label), element('div', 'value', formatter(stats[key])));
      if (!finite(stats[key])) metric.append(element('div', 'reason', text(stats.metric_status?.[key], 'Metric unavailable')));
      grid.append(metric);
    });
    return grid;
  }

  function details(title, content) {
    const node = element('details', 'details');
    node.append(element('summary', '', title), content);
    return node;
  }

  function renderHoldings(holdings) {
    if (!holdings.length) return unavailable('No executed holdings were returned.');
    return table(['Decision / execution', 'Period end', 'Signed target weights', 'Turnover', 'Trading', 'Funding', 'Borrow', 'Net return'], holdings.map((row) => {
      const dates = element('span');
      dates.append(document.createTextNode(date(row.decision_date)), element('span', 'asset-name', `Execute ${date(row.execution_date)}`));
      const weights = element('span', 'weights');
      weights.textContent = Object.entries(row.weights || {}).map(([symbol, weight]) => `${symbol} ${percent(weight, true)}`).join(' · ') || 'Unavailable';
      return [dates, date(row.end_date), weights, percent(row.turnover), percent(row.trading_cost), percent(row.funding_cost), percent(row.borrow_cost), element('span', tone(row.period_return), percent(row.period_return, true))];
    }), 'Weights are signed target exposures. Costs are fractions of starting NAV; source decision and execution dates are retained.');
  }

  function renderDiagnostics(value) {
    const data = element('pre', 'small muted diagnostics');
    data.textContent = JSON.stringify(value || {}, null, 2);
    return data;
  }

  function renderResults(data, params) {
    const output = document.createDocumentFragment();
    const provenance = element('div', 'run-provenance');
    provenance.append(element('h3', '', 'Matched research run'));
    const summary = element('div', 'provenance-grid');
    [
      ['Dataset', data.dataset_id], ['Model', data.model_version], ['Requested', `${params.start} → ${params.end || 'dataset cutoff'}`],
      ['Trading', `${number(params.cost_bps, 1)} bps`], ['Borrow', `${number(params.short_borrow_bps, 1)} bps / year`], ['Rebalance', params.rebalance],
    ].forEach(([label, value]) => { const node = element('span'); node.append(document.createTextNode(`${label}: `), element('b', '', value)); summary.append(node); });
    provenance.append(summary);
    const period = data.period;
    provenance.append(element('p', 'small muted', `Warm-up from ${date(period.warmup_start)} · first decision ${date(period.first_decision)} · first execution ${date(period.first_execution)} · first return ${date(period.first_return)} · last completed return ${date(period.last_complete_return)} · ${finite(period.complete_periods) ? period.complete_periods : 'Unavailable'} completed periods.`));
    if (period.excluded_partial) provenance.append(element('p', 'small muted', 'The incomplete final period is excluded from completed-period statistics.'));
    if (Object.values(data.results).some((result) => result.status === 'ruined')) provenance.append(element('p', 'negative small', 'A strategy reached its terminal loss condition. Its curve stops at ruin; unavailable metrics retain their reason.'));
    const download = element('button', 'button secondary', 'Download this run · JSON');
    download.type = 'button';
    download.addEventListener('click', () => {
      const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' }));
      const link = element('a');
      link.href = url;
      link.download = `radar-${params.mode}-${params.start}.json`;
      link.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    });
    provenance.append(download);
    output.append(provenance);
    const entries = Object.entries(data.results);
    const colors = { extreme1: '#7de0c5', ranked3: '#91b5ff', longonly3: '#e8ba83' };
    if (entries.length > 1) {
      const comparison = element('article', 'card stat-comparison');
      comparison.append(element('h3', 'results-title', 'Strategy comparison'));
      comparison.append(element('p', 'result-subtitle', 'One dataset. Matching assumptions. Each strategy retains its own exposures and outcome.'));
      const lines = entries.map(([mode, result]) => ({ label: strategyLabels[mode], color: colors[mode], points: result.equity_curve.map((row) => ({ date: row.date, value: row.strategy })) }));
      const longestCurve = entries.reduce((longest, [, result]) => Date.parse(result.equity_curve.at(-1)?.date) > Date.parse(longest.at(-1)?.date || '1900-01-01') ? result.equity_curve : longest, []);
      lines.push({ label: 'SPY benchmark', color: '#9ca8b9', points: longestCurve.map((row) => ({ date: row.date, value: row.benchmark })) });
      comparison.append(chart(lines, 'Strategy comparison equity curves'));
      comparison.append(table(['Strategy', 'CAGR', 'Volatility', 'Sharpe', 'Monthly drawdown', 'Status'], entries.map(([mode, result]) => [strategyLabels[mode], percent(result.stats.cagr), percent(result.stats.annualized_volatility), number(result.stats.sharpe), percent(result.stats.max_drawdown_monthly), text(result.status)])));
      output.append(comparison);
    }
    entries.forEach(([mode, result]) => {
      const card = element('article', 'card strategy-result');
      card.dataset.strategy = mode;
      const heading = element('div', 'card-heading');
      heading.append(element('h3', 'results-title', text(result.strategy.label, strategyLabels[mode])), badge(result.status === 'complete' ? 'success' : 'unavailable', text(result.status)));
      card.append(heading);
      card.append(element('p', 'result-subtitle', `Long ${percent(result.strategy.long_gross)} · Short ${percent(result.strategy.short_gross)} · Gross ${percent(result.strategy.gross)} · Net ${percent(result.strategy.net)} · ${finite(result.stats.periods) ? result.stats.periods : 'Unavailable'} periods`));
      if (result.terminal_date) card.append(element('p', 'negative small', `Terminal loss on ${date(result.terminal_date)}. Trading stopped.`));
      card.append(renderMetrics(result.stats));
      card.append(chart([
        { label: strategyLabels[mode], color: colors[mode], points: result.equity_curve.map((row) => ({ date: row.date, value: row.strategy })) },
        { label: 'SPY benchmark', color: '#9ca8b9', points: result.equity_curve.map((row) => ({ date: row.date, value: row.benchmark })) },
      ], `${strategyLabels[mode]} and SPY equity curve`));
      card.append(details(`Executed holdings · ${result.holdings.length} periods`, renderHoldings(result.holdings)));
      card.append(details('Decision scores and macro states', table(['Decision', 'Sector scores', 'Normalized macro states'], result.holdings.map((row) => {
        const scores = element('span', 'weights', list(row.scores).map((entry) => `${text(entry.symbol)}: ${number(entry.score)}`).join(' · ') || 'Unavailable');
        const states = element('span', 'weights', Object.entries(row.state || {}).map(([factor, value]) => `${factor}: ${number(value)}`).join(' · ') || 'Unavailable');
        return [date(row.decision_date), scores, states];
      }))));
      card.append(details('Equity observations', table(['Date', 'Strategy NAV', 'SPY NAV'], result.equity_curve.map((row) => [date(row.date), number(row.strategy), number(row.benchmark)]))));
      const assumptions = element('ul');
      list(result.assumptions).forEach((assumption) => assumptions.append(element('li', '', assumption)));
      card.append(details('Model and execution assumptions', assumptions));
      card.append(details('Calculation diagnostics', renderDiagnostics(result.diagnostics)));
      output.append(card);
    });
    return output;
  }

  async function runBacktest(event) {
    event.preventDefault();
    if (fileMode || !$('backtest-form').reportValidity()) return;
    const params = readParams();
    if (params.end && params.end <= params.start) {
      $('end').setCustomValidity('Evaluation end must be after the start date.');
      $('end').reportValidity();
      return;
    }
    const sequence = ++runSequence;
    runController?.abort();
    runController = new AbortController();
    const controller = runController;
    setState('run', { phase: 'loading', params, result: null });
    $('backtest-fields').disabled = true;
    $('run-results').replaceChildren();
    $('run-results').setAttribute('aria-busy', 'true');
    $('run-error').hidden = true;
    $('run-status').textContent = 'Running research · checking history, availability and execution assumptions…';
    $('run-status').dataset.phase = 'loading';
    const query = new URLSearchParams();
    Object.entries(params).forEach(([key, value]) => { if (value !== null) query.set(key, value); });
    try {
      const data = await request(`/api/backtest?${query}`, controller);
      if (sequence !== runSequence) return;
      validateRun(data, params);
      const result = renderResults(data, params);
      if (sequence !== runSequence) return;
      setState('run', { phase: 'success', params, result: data });
      $('run-results').replaceChildren(result);
      $('run-status').textContent = `Research complete · ${Object.keys(data.results).length} ${params.mode === 'compare' ? 'strategies' : 'strategy'} · Dataset ${data.dataset_id} · Model ${data.model_version}`;
      $('run-status').dataset.phase = 'success';
    } catch (error) {
      if (sequence !== runSequence) return;
      setState('run', { phase: 'error', params, result: null, error: error.message });
      $('run-results').replaceChildren();
      $('run-error').textContent = error.message;
      $('run-error').hidden = false;
      $('run-status').textContent = 'Research unavailable · no result published for these parameters.';
      $('run-status').dataset.phase = 'error';
    } finally {
      if (sequence === runSequence) {
        $('backtest-fields').disabled = false;
        $('run-results').setAttribute('aria-busy', 'false');
      }
    }
  }

  $('refresh-market').addEventListener('click', loadMarket);
  $('backtest-form').addEventListener('submit', runBacktest);
  $('backtest-form').addEventListener('input', invalidateRun);
  $('backtest-form').addEventListener('change', invalidateRun);
  window.addEventListener('pagehide', () => { marketController?.abort(); runController?.abort(); });
  $('derived-panels').replaceChildren(renderPanels(null));
  if (fileMode) {
    $('file-notice').hidden = false;
    $('refresh-market').disabled = true;
    $('backtest-fields').disabled = true;
    $('market-status').textContent = 'Local server required';
    $('run-status').textContent = 'Start the local server to run research.';
  } else loadMarket();
})();
