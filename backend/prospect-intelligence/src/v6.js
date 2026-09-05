import engine from './v4.js';

const ORIGIN = 'https://leadflowautomations.github.io';
const ALLOWED = new Set([ORIGIN, 'https://leadflowautomations-github-io.pages.dev']);

function cors(origin) {
  return {
    'Access-Control-Allow-Origin': ALLOWED.has(origin) ? origin : ORIGIN,
    'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
    'Access-Control-Allow-Headers': 'Content-Type, Accept',
    'Access-Control-Max-Age': '86400',
    'Access-Control-Expose-Headers': 'Content-Type',
    'Vary': 'Origin',
    'Cache-Control': 'no-store'
  };
}

export default {
  async fetch(request, env, ctx) {
    const origin = request.headers.get('Origin') || ORIGIN;
    if (request.method === 'OPTIONS') {
      return new Response(null, { status: 204, headers: cors(origin) });
    }
    try {
      const response = await engine.fetch(request, env, ctx);
      const headers = new Headers(response.headers);
      const c = cors(origin);
      for (const [key, value] of Object.entries(c)) headers.set(key, value);
      return new Response(response.body, { status: response.status, statusText: response.statusText, headers });
    } catch (error) {
      return new Response(JSON.stringify({ ok: false, error: error?.message || 'Prospect research failed' }), {
        status: 500,
        headers: { ...cors(origin), 'Content-Type': 'application/json; charset=utf-8' }
      });
    }
  }
};
