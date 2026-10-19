// Transitional Node handler adapter. Never used as a second financial engine.
export function legacyProxy(path) {
  return async function handler(req, res) {
    res.setHeader('Cache-Control', 'no-store');
    if (req.method !== 'GET') {
      res.setHeader('Allow', 'GET');
      return res.status(405).json({ ok: false, error: { code: 'method_not_allowed', message: 'Use GET.' } });
    }
    const base = process.env.RADAR_PYTHON_API_URL;
    if (!base) return res.status(503).json({ ok: false, error: {
      code: 'migration_required', message: 'Run the Python app and set RADAR_PYTHON_API_URL for legacy Node consumers.'
    } });
    try {
      const url = new URL(path, base);
      for (const [key, value] of Object.entries(req.query || {})) {
        for (const item of Array.isArray(value) ? value : [value]) url.searchParams.append(key, String(item));
      }
      const upstream = await fetch(url, { signal: AbortSignal.timeout(20000), redirect: 'error' });
      const reader = upstream.body.getReader();
      const chunks = [];
      let bytes = 0;
      try {
        for (;;) {
          const { done, value } = await reader.read();
          if (done) break;
          bytes += value.length;
          if (bytes > 2 * 1024 * 1024) throw new Error('Result limit');
          chunks.push(value);
        }
      } finally { await reader.cancel(); }
      const body = JSON.parse(Buffer.concat(chunks).toString('utf8'));
      return res.status(upstream.status).json(body);
    } catch {
      return res.status(503).json({ ok: false, error: { code: 'service_unavailable', message: 'Python radar service unavailable.' } });
    }
  };
}
