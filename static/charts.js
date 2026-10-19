/* Native SVG presentation. Values and units are supplied by the calculation API. */
(() => {
  'use strict';

  const NS = 'http://www.w3.org/2000/svg';
  const finite = (value) => typeof value === 'number' && Number.isFinite(value);
  const list = (value) => Array.isArray(value) ? value : [];
  const palettes = [
    { name: 'green', color: '#29d49a' },
    { name: 'blue', color: '#4ea5ff' },
    { name: 'amber', color: '#f2bc55' },
    { name: 'gray', color: '#91a4bd' },
    { name: 'cyan', color: '#4bd9ff' },
    { name: 'coral', color: '#f06673' },
    { name: 'purple', color: '#9b83ff' },
    { name: 'pink', color: '#e8a3db' },
  ];
  const legacyColors = { '#7de0c5': 0, '#91b5ff': 1, '#e8ba83': 2, '#9ca8b9': 3 };
  let chartId = 0;
  let resizeObserver;
  const observed = new WeakMap();

  const element = (tag, className, value) => {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (value !== undefined) node.textContent = value;
    return node;
  };
  const svgElement = (tag, attributes = {}, value) => {
    const node = document.createElementNS(NS, tag);
    Object.entries(attributes).forEach(([name, content]) => node.setAttribute(name, content));
    if (value !== undefined) node.textContent = value;
    return node;
  };
  const formatNumber = (value, digits) => value.toLocaleString('en-US', {
    minimumFractionDigits: digits, maximumFractionDigits: digits,
  });

  function unitFormat(unit) {
    const key = String(unit || 'NAV').toLowerCase().replaceAll('_', ' ').trim();
    if (key === 'fraction') return { label: '%', factor: 100, suffix: '%', digits: 2 };
    if (['percent', '%', 'percentage'].includes(key)) return { label: '%', factor: 1, suffix: '%', digits: 2 };
    if (['percentage points', 'pp'].includes(key)) return { label: 'pp', factor: 1, suffix: ' pp', digits: 2, zero: true };
    if (['basis points', 'bps', 'bp'].includes(key)) return { label: 'bps', factor: 1, suffix: ' bps', digits: 1, zero: true };
    if (key === 'score') return { label: 'Score', factor: 1, suffix: '', digits: 1, zero: true };
    if (key === 'correlation') return { label: 'Correlation', factor: 1, suffix: '', digits: 2, zero: true };
    if (key === 'ratio') return { label: 'Ratio', factor: 1, suffix: '×', digits: 2 };
    return { label: String(unit || 'NAV'), factor: 1, suffix: '', digits: 2 };
  }

  function watchSize(wrapper, redraw) {
    if (!window.ResizeObserver) return;
    if (!resizeObserver) {
      resizeObserver = new ResizeObserver((entries) => entries.forEach((entry) => {
        if (entry.contentRect.width > 0) observed.get(entry.target)?.(entry.contentRect.width);
      }));
      // Repeated refreshes replace chart nodes. Release their observers with the old DOM.
      new MutationObserver((records) => records.forEach((record) => record.removedNodes.forEach((node) => {
        if (!(node instanceof Element)) return;
        const removed = node.matches('.signal-chart') ? [node] : [...node.querySelectorAll('.signal-chart')];
        removed.forEach((chart) => {
          if (!chart.isConnected) {
            resizeObserver.unobserve(chart);
            observed.delete(chart);
          }
        });
      }))).observe(document.documentElement, { childList: true, subtree: true });
    }
    observed.set(wrapper, redraw);
    resizeObserver.observe(wrapper);
  }

  function render(series, title, valueLabel = 'NAV') {
    const valid = list(series).filter((item) => item && list(item.points).some((point) => finite(point?.value) && typeof point.date === 'string'))
      .map((item, index) => {
        const explicit = typeof item.color === 'string' ? item.color.toLowerCase() : '';
        const palette = palettes.find((color) => color.color === explicit) || palettes[legacyColors[explicit] ?? index % palettes.length];
        return { label: typeof item.label === 'string' ? item.label : `Series ${index + 1}`, points: list(item.points), ...palette };
      });
    if (!valid.length) return element('p', 'empty-state', 'No chart observations available.');
    const rawPoints = valid.flatMap((item) => item.points).filter((point) => typeof point?.date === 'string');
    const numericPoints = rawPoints.filter((point) => finite(point.value));
    const isDated = numericPoints.every((point) => /^\d{4}-\d{2}-\d{2}/.test(point.date) && finite(Date.parse(point.date)));
    const categories = [...new Set(rawPoints.map((point) => point.date))];
    const categoryIndex = new Map(categories.map((label, index) => [label, index]));
    const position = (label) => isDated ? Date.parse(label) : categoryIndex.get(label);
    const positions = [...new Set(rawPoints.map((point) => position(point.date)).filter(finite))].sort((a, b) => a - b);
    if (!positions.length) return element('p', 'empty-state', 'No chart observations available.');
    const unit = unitFormat(valueLabel);
    const displayValue = (value, axis = false, digits = unit.digits) => finite(value)
      ? `${formatNumber(value * unit.factor, axis ? digits : unit.digits)}${unit.suffix}` : '—';
    const dateLabel = (value, compact = false) => {
      if (!isDated) return categories[value] || '';
      const instant = new Date(value);
      return compact ? new Intl.DateTimeFormat('en-US', { month: 'short', day: 'numeric', timeZone: 'UTC' }).format(instant) : instant.toISOString().slice(0, 10);
    };
    valid.forEach((item) => {
      item.lookup = new Map(item.points.filter((point) => typeof point?.date === 'string').map((point) => [position(point.date), point.value]));
      item.latest = item.points.filter((point) => finite(point?.value) && finite(position(point.date))).at(-1);
    });
    const minTime = positions[0], maxTime = positions.at(-1);
    const values = numericPoints.filter((point) => finite(position(point.date))).map((point) => point.value);
    const barChart = !isDated && categories.every((label) => /^\d{4}$/.test(label)) && /annual|yearly/i.test(title);
    const includeZero = unit.zero || barChart || /drawdown|excess return|subsequent.*return/i.test(title);
    const minimum = Math.min(...values, ...(includeZero ? [0] : []));
    const maximum = Math.max(...values, ...(includeZero ? [0] : []));
    const margin = Math.max((maximum - minimum) * .09, Math.abs(maximum) * .012, .01);
    const low = minimum - margin, high = maximum + margin;
    const axisSpan = (high - low) * unit.factor;
    const magnitude = 10 ** Math.floor(Math.log10(axisSpan / 4));
    const ratio = axisSpan / 4 / magnitude;
    const stepFactor = [1, 2, 2.5, 5, 10].find((step) => step >= ratio) || 10;
    const step = stepFactor * magnitude;
    const tickDigits = Math.max(0, -Math.floor(Math.log10(step))) + (stepFactor === 2.5 ? 1 : 0);
    const ticks = [];
    for (let tick = Math.ceil(low * unit.factor / step) * step; tick <= high * unit.factor + step / 100; tick += step) ticks.push(Math.abs(tick) < step / 100 ? 0 : tick / unit.factor);
    const id = `radar-chart-${++chartId}`;
    const wrapper = element('div', 'signal-chart');
    const plot = element('div', 'chart-wrap signal-chart-plot');
    plot.tabIndex = 0;
    plot.setAttribute('role', 'group');
    plot.setAttribute('aria-label', `${title}. Use left and right arrow keys to inspect observations; Home and End jump to the first and last.`);
    plot.setAttribute('aria-describedby', `${id}-readout`);
    const svg = svgElement('svg', { class: 'chart signal-chart-svg', role: 'img', 'aria-label': title });
    plot.append(svg);
    const readout = element('div', 'chart-readout');
    readout.id = `${id}-readout`;
    const readoutDate = element('span', 'chart-readout-date');
    const readoutValues = element('div', 'chart-readout-values');
    readout.append(readoutDate, readoutValues);
    const instruction = element('div', 'chart-instruction', 'Move across the chart or use ← → to inspect');
    const announcement = element('span', 'chart-sr-only');
    announcement.setAttribute('aria-live', 'polite');
    const legend = element('div', 'chart-legend signal-chart-legend');
    legend.append(element('span', 'chart-legend-context', isDated ? 'Latest' : 'Last point'));
    const legendButtons = valid.map((item, index) => {
      const button = element('button', `legend-item chart-series-key chart-tone-${item.name}`);
      button.type = 'button';
      button.title = `Emphasize ${item.label}`;
      button.setAttribute('aria-pressed', index === 0 ? 'true' : 'false');
      button.append(element('span', 'legend-line'), element('span', 'chart-key-label', item.label));
      const latest = element('strong', 'chart-key-value', displayValue(item.latest?.value));
      latest.title = item.latest ? `Latest observed: ${dateLabel(position(item.latest.date))}` : 'Unavailable';
      button.append(latest);
      button.addEventListener('click', () => selectSeries(index));
      legend.append(button);
      return button;
    });
    wrapper.append(plot, readout, legend, instruction, announcement);

    let selectedSeries = 0;
    let selectedPoint = positions.length - 1;
    let cursor;
    let cursorDots = [];
    let x;
    let y;
    let width;
    let height;
    let left;
    let right;
    let top;
    let bottom;

    function selectSeries(index) {
      selectedSeries = index;
      svg.querySelectorAll('[data-series]').forEach((node) => node.classList.toggle('is-focused', Number(node.getAttribute('data-series')) === selectedSeries));
      legendButtons.forEach((button, current) => button.setAttribute('aria-pressed', current === index ? 'true' : 'false'));
    }

    function inspect(index, announce = false) {
      selectedPoint = Math.max(0, Math.min(positions.length - 1, index));
      const current = positions[selectedPoint];
      readoutDate.textContent = dateLabel(current);
      readoutValues.replaceChildren(...valid.map((item) => {
        const cell = element('span', `chart-readout-item chart-tone-${item.name}`);
        cell.append(element('span', '', item.label), element('strong', '', displayValue(item.lookup.get(current))));
        return cell;
      }));
      if (cursor) {
        cursor.setAttribute('x1', x(current));
        cursor.setAttribute('x2', x(current));
      }
      cursorDots.forEach((dot, seriesIndex) => {
        const value = valid[seriesIndex].lookup.get(current);
        dot.setAttribute('visibility', finite(value) ? 'visible' : 'hidden');
        if (finite(value)) {
          dot.setAttribute('cx', x(current));
          dot.setAttribute('cy', y(value));
        }
      });
      if (announce) announcement.textContent = `${dateLabel(current)}. ${valid.map((item) => `${item.label}: ${displayValue(item.lookup.get(current))}`).join('. ')}`;
    }

    function draw(containerWidth = 820) {
      const nextWidth = Math.max(280, Math.min(1000, Math.round(containerWidth)));
      if (width === nextWidth) return;
      width = nextWidth;
      height = width < 480 ? 240 : 280;
      const labelWidth = Math.max(...ticks.map((tick) => displayValue(tick, true, tickDigits).length)) * 5.7 + 10;
      left = Math.min(width < 480 ? 78 : 96, Math.max(width < 480 ? 48 : 60, labelWidth));
      right = 18;
      top = 25;
      bottom = 36;
      const plotWidth = width - left - right;
      const groupWidth = barChart ? plotWidth / positions.length : 0;
      x = (value) => barChart ? left + groupWidth * (value + .5)
        : positions.length === 1 ? left + plotWidth / 2 : left + (value - minTime) / (maxTime - minTime || 1) * plotWidth;
      y = (value) => top + (high - value) / (high - low) * (height - top - bottom);
      svg.setAttribute('viewBox', `0 0 ${width} ${height}`);
      svg.replaceChildren(svgElement('title', {}, title), svgElement('desc', {}, `${unit.label}. ${dateLabel(minTime)} to ${dateLabel(maxTime)}. Colored series correspond to the legend. Missing values break the line. Inspect individual observations with the arrow keys.`));
      svg.append(svgElement('text', { x: left, y: 12, class: 'chart-unit' }, unit.label));
      ticks.forEach((value) => {
        svg.append(svgElement('line', { x1: left, x2: width - right, y1: y(value), y2: y(value), class: 'chart-grid' }));
        svg.append(svgElement('text', { x: left - 8, y: y(value) + 4, 'text-anchor': 'end', class: 'chart-axis-label' }, displayValue(value, true, tickDigits)));
      });
      if (low < 0 && high > 0) svg.append(svgElement('line', { x1: left, x2: width - right, y1: y(0), y2: y(0), class: 'chart-zero' }));
      const labelCount = width < 480 ? 3 : 5;
      const labelPositions = !isDated && positions.length <= (width < 480 ? 7 : 12) ? positions : [...new Set(Array.from({ length: Math.min(labelCount, positions.length) }, (_, index) => positions[Math.round(index * (positions.length - 1) / (Math.min(labelCount, positions.length) - 1 || 1))]))];
      labelPositions.forEach((value, index) => svg.append(svgElement('text', {
        x: x(value), y: height - 10, 'text-anchor': barChart ? 'middle' : index === 0 ? 'start' : index === labelPositions.length - 1 ? 'end' : 'middle', class: 'chart-axis-label',
      }, isDated && width < 480 ? dateLabel(value, true) : dateLabel(value))));

      valid.forEach((item, seriesIndex) => {
        if (barChart) {
          const barWidth = Math.min(26, groupWidth * .72 / valid.length);
          item.points.forEach((point) => {
            if (!finite(point?.value) || !finite(position(point.date))) return;
            const center = x(position(point.date)) + (seriesIndex - (valid.length - 1) / 2) * barWidth;
            svg.append(svgElement('rect', { x: center - barWidth / 2 + 1, y: Math.min(y(0), y(point.value)), width: Math.max(1, barWidth - 2), height: Math.max(.5, Math.abs(y(point.value) - y(0))), rx: 2, fill: item.color, class: 'chart-bar', 'data-series': seriesIndex }));
          });
          return;
        }
        let drawing = false;
        const segments = [];
        let segment = [];
        const path = item.points.map((point) => {
          if (!finite(point?.value) || typeof point.date !== 'string' || !finite(position(point.date))) {
            drawing = false;
            if (segment.length) segments.push(segment);
            segment = [];
            return '';
          }
          const command = drawing ? 'L' : 'M';
          drawing = true;
          const coords = `${x(position(point.date)).toFixed(2)},${y(point.value).toFixed(2)}`;
          segment.push([x(position(point.date)), y(point.value)]);
          return `${command}${coords}`;
        }).join(' ');
        if (segment.length) segments.push(segment);
        if (valid.length === 1) segments.filter((points) => points.length > 1).forEach((points) => {
          const baseline = low < 0 && high > 0 ? y(0) : height - bottom;
          const area = `M${points[0][0]},${baseline} ${points.map((point) => `L${point[0]},${point[1]}`).join(' ')} L${points.at(-1)[0]},${baseline}Z`;
          svg.append(svgElement('path', { d: area, fill: item.color, class: 'chart-area' }));
        });
        svg.append(svgElement('path', { d: path, fill: 'none', stroke: item.color, class: 'chart-series', 'data-series': seriesIndex, 'vector-effect': 'non-scaling-stroke' }));
        if (!isDated || item.points.length === 1) item.points.forEach((point) => {
          if (finite(point?.value) && finite(position(point.date))) svg.append(svgElement('circle', { cx: x(position(point.date)), cy: y(point.value), r: 3, fill: item.color, class: 'chart-observation', 'data-series': seriesIndex }));
        });
        if (item.latest) svg.append(svgElement('circle', { cx: x(position(item.latest.date)), cy: y(item.latest.value), r: 4, fill: item.color, class: 'chart-endpoint', 'data-series': seriesIndex }));
      });
      cursor = svgElement('line', { x1: 0, x2: 0, y1: top, y2: height - bottom, class: 'chart-cursor' });
      svg.append(cursor);
      cursorDots = valid.map((item) => {
        const dot = svgElement('circle', { r: 4, fill: item.color, class: 'chart-cursor-dot' });
        svg.append(dot);
        return dot;
      });
      selectSeries(selectedSeries);
      inspect(selectedPoint);
    }

    plot.addEventListener('pointermove', (event) => {
      const rect = svg.getBoundingClientRect();
      if (!rect.width) return;
      const relative = (event.clientX - rect.left) / rect.width * width;
      let nearest = 0;
      positions.forEach((value, index) => {
        if (Math.abs(x(value) - relative) < Math.abs(x(positions[nearest]) - relative)) nearest = index;
      });
      if (nearest !== selectedPoint) inspect(nearest);
    });
    plot.addEventListener('keydown', (event) => {
      const next = { ArrowLeft: selectedPoint - 1, ArrowRight: selectedPoint + 1, Home: 0, End: positions.length - 1 }[event.key];
      if (next !== undefined) {
        event.preventDefault();
        inspect(next, true);
      }
    });
    draw();
    watchSize(wrapper, draw);
    const result = document.createDocumentFragment();
    result.append(wrapper);
    return result;
  }

  window.RadarCharts = Object.freeze({ render });
})();
