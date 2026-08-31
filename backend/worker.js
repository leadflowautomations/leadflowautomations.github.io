/** Lead Flow Automation — Cloudflare Worker backend scaffold
 * Secrets are supplied through Cloudflare bindings/environment, never committed here.
 */
const json = (data, status = 200) => new Response(JSON.stringify(data), { status, headers: { 'content-type': 'application/json; charset=utf-8', 'cache-control': 'no-store' } });
const allowedOrigin = (env) => env.ALLOWED_ORIGIN || 'https://leadflowautomations.github.io';

function cors(request, env) {
  const origin = request.headers.get('Origin');
  if (origin && origin !== allowedOrigin(env)) return null;
  return { 'access-control-allow-origin': origin || allowedOrigin(env), 'access-control-allow-methods': 'GET,POST,OPTIONS', 'access-control-allow-headers': 'Content-Type', 'vary': 'Origin' };
}

export default {
  async fetch(request, env) {
    const headers = cors(request, env);
    if (!headers) return json({ error: 'Origin not allowed' }, 403);
    if (request.method === 'OPTIONS') return new Response(null, { status: 204, headers });

    const url = new URL(request.url);
    if (url.pathname === '/api/health' && request.method === 'GET') return new Response(JSON.stringify({ ok: true, service: 'leadflow-api' }), { headers: { ...headers, 'content-type': 'application/json', 'cache-control': 'no-store' } });

    if (url.pathname === '/api/leads' && request.method === 'POST') {
      let body;
      try { body = await request.json(); } catch { return new Response(JSON.stringify({ error: 'Invalid JSON' }), { status: 400, headers: { ...headers, 'content-type': 'application/json' } }); }
      const required = ['name', 'email', 'consent'];
      if (!required.every(k => body[k]) || body.consent !== true) return new Response(JSON.stringify({ error: 'Name, email and consent are required.' }), { status: 400, headers: { ...headers, 'content-type': 'application/json' } });
      if (!/^\S+@\S+\.\S+$/.test(String(body.email))) return new Response(JSON.stringify({ error: 'Invalid email.' }), { status: 400, headers: { ...headers, 'content-type': 'application/json' } });
      const lead = { id: crypto.randomUUID(), name: String(body.name).slice(0,120), email: String(body.email).slice(0,254), businessType: String(body.businessType || '').slice(0,100), need: String(body.need || '').slice(0,100), package: String(body.package || '').slice(0,100), timeline: String(body.timeline || '').slice(0,100), consent: true, createdAt: new Date().toISOString() };
      if (env.DB) await env.DB.prepare('INSERT INTO leads (id,name,email,business_type,need,package,timeline,consent,created_at) VALUES (?,?,?,?,?,?,?,?,?)').bind(lead.id, lead.name, lead.email, lead.businessType, lead.need, lead.package, lead.timeline, 1, lead.createdAt).run();
      return new Response(JSON.stringify({ ok: true, leadId: lead.id }), { status: 201, headers: { ...headers, 'content-type': 'application/json' } });
    }

    return new Response(JSON.stringify({ error: 'Not found' }), { status: 404, headers: { ...headers, 'content-type': 'application/json' } });
  }
};
