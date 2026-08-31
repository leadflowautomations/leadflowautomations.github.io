/** Lead Flow Automation — Cloudflare Worker backend
 * Secrets are supplied through Cloudflare bindings/environment, never committed here.
 */
const json = (data, status = 200, headers = {}) => new Response(JSON.stringify(data), { status, headers: { 'content-type': 'application/json; charset=utf-8', 'cache-control': 'no-store', ...headers } });
const allowedOrigin = (env) => env.ALLOWED_ORIGIN || 'https://leadflowautomations.github.io';

function cors(request, env) {
  const origin = request.headers.get('Origin');
  if (origin && origin !== allowedOrigin(env)) return null;
  return { 'access-control-allow-origin': origin || allowedOrigin(env), 'access-control-allow-methods': 'GET,POST,OPTIONS', 'access-control-allow-headers': 'Content-Type', 'vary': 'Origin' };
}

export default {
  async fetch(request, env) {
    const headers = cors(request, env);
    if (!headers) return json({ error: 'Origin not allowed' }, 403, headers || {});
    if (request.method === 'OPTIONS') return new Response(null, { status: 204, headers });

    const url = new URL(request.url);
    if (url.pathname === '/api/health' && request.method === 'GET') {
      return json({ ok: true, service: 'leadflow-api' }, 200, headers);
    }

    if (url.pathname === '/api/leads' && request.method === 'POST') {
      let body;
      try { body = await request.json(); } catch { return json({ error: 'Invalid JSON' }, 400, headers); }

      const required = ['businessName', 'name', 'email', 'consent'];
      if (!required.every(k => body[k]) || body.consent !== true) {
        return json({ error: 'Business name, name, email and consent are required.' }, 400, headers);
      }
      if (!/^\S+@\S+\.\S+$/.test(String(body.email))) {
        return json({ error: 'Invalid email.' }, 400, headers);
      }

      // The existing D1 table intentionally keeps a small privacy-focused shape.
      // Preserve the business name without requiring a live schema migration by
      // storing it alongside the contact name in the existing name column.
      const displayName = `${String(body.name).slice(0, 120)} — ${String(body.businessName).slice(0, 120)}`;
      const lead = {
        id: crypto.randomUUID(),
        name: displayName.slice(0, 240),
        email: String(body.email).slice(0, 254),
        businessType: String(body.businessType || '').slice(0, 100),
        need: String(body.need || '').slice(0, 100),
        package: String(body.packageInterest || body.package || '').slice(0, 100),
        timeline: String(body.timeline || '').slice(0, 100),
        consent: true,
        createdAt: new Date().toISOString()
      };

      if (env.DB) {
        await env.DB.prepare('INSERT INTO leads (id,name,email,business_type,need,package,timeline,consent,created_at) VALUES (?,?,?,?,?,?,?,?,?)')
          .bind(lead.id, lead.name, lead.email, lead.businessType, lead.need, lead.package, lead.timeline, 1, lead.createdAt)
          .run();
      }

      return json({ ok: true, leadId: lead.id }, 201, headers);
    }

    return json({ error: 'Not found' }, 404, headers);
  }
};
