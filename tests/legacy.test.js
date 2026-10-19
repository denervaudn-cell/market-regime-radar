import test from 'node:test';
import assert from 'node:assert/strict';
import market from '../market.js';
import backtest from '../backtest.js';

function response() {
  return { headers: {}, setHeader(k, v) { this.headers[k] = v; }, status(v) { this.code = v; return this; }, json(v) { this.body = v; return this; } };
}

test('legacy handlers reject writes without acquiring data', async () => {
  for (const handler of [market, backtest]) {
    const res = response();
    await handler({ method: 'POST' }, res);
    assert.equal(res.code, 405);
    assert.equal(res.headers.Allow, 'GET');
    assert.equal(res.headers['Cache-Control'], 'no-store');
  }
});

test('an unconfigured legacy consumer gets a migration outcome', async () => {
  const previous = process.env.RADAR_PYTHON_API_URL;
  delete process.env.RADAR_PYTHON_API_URL;
  try {
    const res = response();
    await backtest({ method: 'GET' }, res);
    assert.equal(res.code, 503);
    assert.equal(res.body.error.code, 'migration_required');
  } finally {
    if (previous === undefined) delete process.env.RADAR_PYTHON_API_URL;
    else process.env.RADAR_PYTHON_API_URL = previous;
  }
});

test('legacy proxy preserves repeated parameters for canonical rejection', async () => {
  const previous = process.env.RADAR_PYTHON_API_URL, originalFetch = globalThis.fetch;
  process.env.RADAR_PYTHON_API_URL = 'https://example.invalid';
  try {
    globalThis.fetch = async (url, options) => {
      assert.equal(url.pathname, '/api/backtest');
      assert.deepEqual(url.searchParams.getAll('start'), ['2020-01-01', '2021-01-01']);
      assert.equal(url.searchParams.get('cost_bps'), '0');
      assert.equal(options.redirect, 'error');
      assert.ok(options.signal instanceof AbortSignal);
      return new Response(JSON.stringify({ ok: false, error: { code: 'invalid_parameters' } }), { status: 400 });
    };
    const res = response();
    await backtest({ method: 'GET', query: { start: ['2020-01-01', '2021-01-01'], cost_bps: 0 } }, res);
    assert.equal(res.code, 400);
    assert.equal(res.body.error.code, 'invalid_parameters');
  } finally {
    globalThis.fetch = originalFetch;
    if (previous === undefined) delete process.env.RADAR_PYTHON_API_URL;
    else process.env.RADAR_PYTHON_API_URL = previous;
  }
});
