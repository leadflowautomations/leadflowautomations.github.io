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

const INDUSTRY_TAGS = {
  'real estate': ['office=estate_agent', 'office=property_management', 'shop=estate_agent'],
  restaurant: ['amenity=restaurant'], restaurants: ['amenity=restaurant'], hotel: ['tourism=hotel'],
  dentist: ['amenity=dentist'], dental: ['amenity=dentist'], 'law firm': ['office=lawyer'], law: ['office=lawyer'],
  accounting: ['office=accountant'], fitness: ['leisure=fitness_centre'], gym: ['leisure=fitness_centre'],
  beauty: ['shop=beauty', 'shop=hairdresser'], salon: ['shop=hairdresser'], 'car dealer': ['shop=car'],
  pharmacy: ['amenity=pharmacy'], cafe: ['amenity=cafe'], school: ['amenity=school'], clinic: ['amenity=clinic']
};

function buildOverpassQuery(tags, lat, lon, radius) {
  const clauses = tags.map(tag => {
    const [key, value] = tag.split('=');
    return `nwr["${key}"="${value}"](around:${radius},${lat},${lon});`;
  }).join('');
  return `[out:json][timeout:55];(${clauses});out center tags;`;
}

function normalizeProspects(elements, country) {
  const seen = new Set();
  const items = [];
  for (const element of elements || []) {
    const tags = element.tags || {};
    const name = String(tags.name || '').trim();
    const lat = element.lat ?? element.center?.lat;
    const lon = element.lon ?? element.center?.lon;
    if (!name || lat == null || lon == null) continue;
    const key = `${name.toLowerCase()}|${Math.round(Number(lat) * 1000)}|${Math.round(Number(lon) * 1000)}`;
    if (seen.has(key)) continue;
    seen.add(key);
    const website = String(tags.website || tags['contact:website'] || '').trim();
    const phone = String(tags.phone || tags['contact:phone'] || '').trim();
    const email = String(tags.email || tags['contact:email'] || '').trim();
    const address = [tags['addr:housenumber'], tags['addr:street'], tags['addr:city']].filter(Boolean).join(' ');
    let score = 40;
    if (website) score += 30;
    if (phone) score += 10;
    if (email) score += 10;
    if (tags['addr:street']) score += 5;
    items.push({
      name, website, phone, email, address: address || country,
      latitude: Number(lat), longitude: Number(lon), score: Math.min(95, score), source: 'OpenStreetMap',
      evidence: [website ? 'Public website listed' : 'No public website listed', phone ? 'Public phone listed' : 'No public phone listed', email ? 'Public email listed' : 'No public email listed']
    });
  }
  return items.sort((a, b) => b.score - a.score);
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

    if (url.pathname === '/api/prospect-search' && request.method === 'GET') {
      const location = (url.searchParams.get('location') || '').trim();
      const country = (url.searchParams.get('country') || '').trim();
      const industry = (url.searchParams.get('industry') || '').trim().toLowerCase();
      const requestedLimit = Number(url.searchParams.get('limit') || 100);
      const limit = Math.min(100, Math.max(1, Number.isFinite(requestedLimit) ? requestedLimit : 100));
      if (!location || !country || !industry) return json({ error: 'location, country and industry are required.' }, 400, headers);

      const tags = INDUSTRY_TAGS[industry] || ['office'];
      const geoUrl = `https://nominatim.openstreetmap.org/search?format=jsonv2&limit=1&q=${encodeURIComponent(`${location}, ${country}`)}`;
      let geoResponse;
      try {
        geoResponse = await fetch(geoUrl, { headers: { accept: 'application/json', 'user-agent': 'LeadFlowAutomation-ProspectResearch/1.0 (+https://leadflowautomations.github.io/)' } });
      } catch (error) {
        return json({ error: 'Location provider could not be reached.', detail: String(error?.message || error) }, 502, headers);
      }
      if (!geoResponse.ok) return json({ error: `Location provider returned HTTP ${geoResponse.status}.` }, 502, headers);
      const geo = await geoResponse.json();
      if (!Array.isArray(geo) || !geo[0]) return json({ error: `Could not locate ${location}, ${country}.` }, 404, headers);

      const lat = Number(geo[0].lat), lon = Number(geo[0].lon);
      const query = buildOverpassQuery(tags, lat, lon, 30000);
      const endpoints = ['https://overpass-api.de/api/interpreter', 'https://overpass.kumi.systems/api/interpreter'];
      let data = null, lastError = null;
      for (const endpoint of endpoints) {
        try {
          const response = await fetch(`${endpoint}?data=${encodeURIComponent(query)}`, { headers: { accept: 'application/json' } });
          if (!response.ok) { lastError = new Error(`HTTP ${response.status}`); continue; }
          data = await response.json();
          break;
        } catch (error) { lastError = error; }
      }
      if (!data) return json({ error: 'Business search provider unavailable.', detail: String(lastError?.message || lastError || 'Unknown error') }, 502, headers);

      const prospects = normalizeProspects(data.elements, country).slice(0, limit);
      return json({ ok: true, query: { location, country, industry }, center: { latitude: lat, longitude: lon }, count: prospects.length, prospects }, 200, headers);
    }

    if (url.pathname === '/api/leads' && request.method === 'POST') {
      let body;
      try { body = await request.json(); } catch { return json({ error: 'Invalid JSON' }, 400, headers); }
      const required = ['businessName', 'name', 'email', 'consent'];
      if (!required.every(k => body[k]) || body.consent !== true) return json({ error: 'Business name, name, email and consent are required.' }, 400, headers);
      if (!/^\S+@\S+\.\S+$/.test(String(body.email))) return json({ error: 'Invalid email.' }, 400, headers);
      const displayName = `${String(body.name).slice(0, 120)} — ${String(body.businessName).slice(0, 120)}`;
      const lead = { id: crypto.randomUUID(), name: displayName.slice(0, 240), email: String(body.email).slice(0, 254), businessType: String(body.businessType || '').slice(0, 100), need: String(body.need || '').slice(0, 100), package: String(body.packageInterest || body.package || '').slice(0, 100), timeline: String(body.timeline || '').slice(0, 100), consent: true, createdAt: new Date().toISOString() };
      if (env.DB) await env.DB.prepare('INSERT INTO leads (id,name,email,business_type,need,package,timeline,consent,created_at) VALUES (?,?,?,?,?,?,?,?,?)').bind(lead.id, lead.name, lead.email, lead.businessType, lead.need, lead.package, lead.timeline, 1, lead.createdAt).run();
      return json({ ok: true, leadId: lead.id }, 201, headers);
    }
    return json({ error: 'Not found' }, 404, headers);
  }
};
