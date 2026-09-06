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

function normalizeProspects(elements, country, industry) {
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
    const matchedTag = Object.entries(tags).find(([k, v]) => INDUSTRY_TAGS[industry]?.includes(`${k}=${v}`));
    let score = 40;
    if (website) score += 30;
    if (phone) score += 10;
    if (email) score += 10;
    if (tags['addr:street']) score += 5;
    items.push({
      name, website, phone, email, address: address || country,
      latitude: Number(lat), longitude: Number(lon), score: Math.min(95, score), source: 'OpenStreetMap',
      industryMatch: matchedTag ? `${matchedTag[0]}=${matchedTag[1]}` : null,
      osmType: element.type, osmId: element.id,
      evidence: [website ? 'Public website listed' : 'No public website listed', phone ? 'Public phone listed' : 'No public phone listed', email ? 'Public email listed' : 'No public email listed']
    });
  }
  return items.sort((a, b) => b.score - a.score);
}

function normalizeName(value) {
  return String(value || '').toLowerCase().normalize('NFKD').replace(/[^a-z0-9]+/g, ' ').replace(/\b(ltd|limited|llc|inc|incorporated|co|company|corp|corporation)\b/g, '').replace(/\s+/g, ' ').trim();
}

function samePlace(a, b) {
  const latA = Number(a.latitude), lonA = Number(a.longitude), latB = Number(b.latitude), lonB = Number(b.longitude);
  if (![latA, lonA, latB, lonB].every(Number.isFinite)) return false;
  return Math.abs(latA - latB) < 0.001 && Math.abs(lonA - lonB) < 0.001;
}

async function checkWebsite(rawUrl) {
  if (!rawUrl) return { checked: false, reachable: false, status: null, url: null, reason: 'No website was listed.' };
  let url = String(rawUrl).trim();
  if (!/^https?:\/\//i.test(url)) url = `https://${url}`;
  try {
    const response = await fetch(url, { method: 'GET', redirect: 'follow', headers: { accept: 'text/html,application/xhtml+xml', 'user-agent': 'LeadFlowAutomation-Verifier/1.0' }, signal: AbortSignal.timeout(8000) });
    return { checked: true, reachable: response.ok, status: response.status, url: response.url || url, reason: response.ok ? 'Website responded successfully.' : `Website responded with HTTP ${response.status}.` };
  } catch (error) {
    return { checked: true, reachable: false, status: null, url, reason: `Website could not be reached: ${String(error?.message || error).slice(0, 140)}` };
  }
}

function verifyDuplicates(prospects) {
  const seen = new Map();
  return prospects.map((p, index) => {
    const nameKey = normalizeName(p.name);
    const websiteKey = String(p.website || '').toLowerCase().replace(/^https?:\/\//, '').replace(/^www\./, '').split('/')[0];
    const candidateKeys = [websiteKey && `web:${websiteKey}`, nameKey && `name:${nameKey}`].filter(Boolean);
    let duplicateOf = null;
    for (const key of candidateKeys) {
      if (seen.has(key)) {
        const prior = seen.get(key);
        if (key.startsWith('web:') || samePlace(p, prior.prospect)) { duplicateOf = prior.index + 1; break; }
      }
    }
    for (const key of candidateKeys) if (!seen.has(key)) seen.set(key, { index, prospect: p });
    return duplicateOf;
  });
}

async function verifyProspects(items, industry) {
  const prospects = Array.isArray(items) ? items.slice(0, 100) : [];
  const duplicateRefs = verifyDuplicates(prospects);
  const checks = await Promise.all(prospects.map(p => checkWebsite(p.website)));
  return prospects.map((p, i) => {
    const website = checks[i];
    const duplicateOf = duplicateRefs[i];
    const categoryMatch = Boolean(p.industryMatch);
    const directoryEvidence = String(p.source || '').toLowerCase() === 'openstreetmap';
    const active = website.checked ? website.reachable : directoryEvidence;
    const activeConfidence = website.checked ? (website.reachable ? 'high' : 'low') : 'medium';
    const categoryConfidence = categoryMatch ? 'high' : 'medium';
    const unique = !duplicateOf;
    const verified = active && categoryMatch && unique;
    const evidence = [
      active ? (website.checked ? 'Website is reachable.' : 'Current public business-directory listing found.') : 'No reliable active-status signal found.',
      categoryMatch ? `Industry category confirmed by directory tag: ${p.industryMatch}.` : `Industry category could not be independently confirmed for ${industry}.`,
      unique ? 'No duplicate found in this discovery batch.' : `Duplicate of result #${duplicateOf} in this discovery batch.`
    ];
    return {
      ...p,
      verification: {
        verified, active, activeConfidence, categoryMatch, categoryConfidence, unique,
        duplicateOf, website, checkedAt: new Date().toISOString(), evidence
      },
      status: verified ? 'verified' : duplicateOf ? 'duplicate' : active && categoryMatch ? 'verified' : 'needs-review'
    };
  });
}

export default {
  async fetch(request, env) {
    const headers = cors(request, env);
    if (!headers) return json({ error: 'Origin not allowed' }, 403, headers || {});
    if (request.method === 'OPTIONS') return new Response(null, { status: 204, headers });

    const url = new URL(request.url);
    if (url.pathname === '/api/health' && request.method === 'GET') return json({ ok: true, service: 'leadflow-api' }, 200, headers);

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
      try { geoResponse = await fetch(geoUrl, { headers: { accept: 'application/json', 'user-agent': 'LeadFlowAutomation-ProspectResearch/1.0 (+https://leadflowautomations.github.io/)' } }); }
      catch (error) { return json({ error: 'Location provider could not be reached.', detail: String(error?.message || error) }, 502, headers); }
      if (!geoResponse.ok) return json({ error: `Location provider returned HTTP ${geoResponse.status}.` }, 502, headers);
      const geo = await geoResponse.json();
      if (!Array.isArray(geo) || !geo[0]) return json({ error: `Could not locate ${location}, ${country}.` }, 404, headers);
      const lat = Number(geo[0].lat), lon = Number(geo[0].lon);
      const query = buildOverpassQuery(tags, lat, lon, 30000);
      const endpoints = ['https://overpass-api.de/api/interpreter', 'https://overpass.kumi.systems/api/interpreter'];
      let data = null, lastError = null;
      for (const endpoint of endpoints) {
        try { const response = await fetch(`${endpoint}?data=${encodeURIComponent(query)}`, { headers: { accept: 'application/json' } }); if (!response.ok) { lastError = new Error(`HTTP ${response.status}`); continue; } data = await response.json(); break; }
        catch (error) { lastError = error; }
      }
      if (!data) return json({ error: 'Business search provider unavailable.', detail: String(lastError?.message || lastError || 'Unknown error') }, 502, headers);
      const prospects = normalizeProspects(data.elements, country, industry).slice(0, limit);
      return json({ ok: true, query: { location, country, industry }, center: { latitude: lat, longitude: lon }, count: prospects.length, prospects }, 200, headers);
    }

    if (url.pathname === '/api/prospect-verify' && request.method === 'POST') {
      let body;
      try { body = await request.json(); } catch { return json({ error: 'Invalid JSON' }, 400, headers); }
      const industry = String(body?.industry || '').trim().toLowerCase();
      const prospects = Array.isArray(body?.prospects) ? body.prospects : [];
      if (!industry || !prospects.length) return json({ error: 'industry and prospects are required.' }, 400, headers);
      if (prospects.length > 100) return json({ error: 'A maximum of 100 prospects can be verified at once.' }, 400, headers);
      const verifiedProspects = await verifyProspects(prospects, industry);
      const verified = verifiedProspects.filter(p => p.verification.verified).length;
      const review = verifiedProspects.filter(p => !p.verification.verified && p.status !== 'duplicate').length;
      const duplicates = verifiedProspects.filter(p => p.status === 'duplicate').length;
      return json({ ok: true, industry, count: verifiedProspects.length, summary: { verified, needsReview: review, duplicates }, prospects: verifiedProspects }, 200, headers);
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