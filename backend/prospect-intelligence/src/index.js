const VERSION = '2026-09-05.1';
const ALLOWED_ORIGINS = new Set([
  'https://leadflowautomations.github.io',
  'https://leadflowautomations-github-io.pages.dev'
]);
const DEFAULT_ORIGIN = 'https://leadflowautomations.github.io';

const INDUSTRY_TAGS = {
  'real estate': ['office=estate_agent', 'office=property_management', 'shop=estate_agent'],
  'real estate agency': ['office=estate_agent', 'office=property_management', 'shop=estate_agent'],
  realtor: ['office=estate_agent', 'shop=estate_agent'],
  property: ['office=estate_agent', 'office=property_management', 'shop=estate_agent'],
  restaurant: ['amenity=restaurant'], restaurants: ['amenity=restaurant'],
  hotel: ['tourism=hotel'], hotels: ['tourism=hotel'],
  dentist: ['amenity=dentist'], dental: ['amenity=dentist'],
  'law firm': ['office=lawyer'], law: ['office=lawyer'], lawyers: ['office=lawyer'],
  accounting: ['office=accountant'], accountant: ['office=accountant'],
  fitness: ['leisure=fitness_centre'], gym: ['leisure=fitness_centre'],
  beauty: ['shop=beauty', 'shop=hairdresser'], salon: ['shop=hairdresser'],
  'car dealer': ['shop=car'], automotive: ['shop=car', 'shop=car_repair'],
  pharmacy: ['amenity=pharmacy'], cafe: ['amenity=cafe'],
  school: ['amenity=school'], clinic: ['amenity=clinic'], medical: ['amenity=clinic', 'amenity=doctors']
};

const INDUSTRY_KEYWORDS = {
  'real estate': ['real estate', 'realty', 'realtor', 'properties', 'property', 'homes', 'brokerage'],
  restaurant: ['restaurant', 'kitchen', 'grill', 'eatery', 'bistro', 'dining'],
  hotel: ['hotel', 'resort', 'inn', 'suites'],
  dentist: ['dentist', 'dental'], dental: ['dentist', 'dental'],
  'law firm': ['law', 'attorney', 'legal'], law: ['law', 'attorney', 'legal'], lawyers: ['law', 'attorney', 'legal'],
  accounting: ['accounting', 'accountant', 'cpa'], accountant: ['accounting', 'accountant', 'cpa'],
  fitness: ['fitness', 'gym', 'training'], gym: ['fitness', 'gym', 'training'],
  beauty: ['beauty', 'salon', 'spa'], salon: ['salon', 'hair'],
  'car dealer': ['auto', 'motors', 'cars', 'dealer'], automotive: ['auto', 'motors', 'cars', 'dealer'],
  pharmacy: ['pharmacy', 'chemist'], cafe: ['cafe', 'coffee'],
  school: ['school', 'academy'], clinic: ['clinic', 'medical', 'health'], medical: ['clinic', 'medical', 'health']
};

function cors(origin) {
  const allowed = ALLOWED_ORIGINS.has(origin);
  return {
    'Access-Control-Allow-Origin': allowed ? origin : DEFAULT_ORIGIN,
    'Access-Control-Allow-Methods': 'GET, OPTIONS',
    'Access-Control-Allow-Headers': 'Content-Type',
    'Access-Control-Max-Age': '86400',
    Vary: 'Origin'
  };
}

function json(data, status = 200, origin = DEFAULT_ORIGIN) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { 'content-type': 'application/json; charset=utf-8', 'cache-control': 'no-store', ...cors(origin) }
  });
}

function clean(value, max = 2000) {
  if (value === null || value === undefined) return '';
  return String(value).trim().slice(0, max);
}

function firstValue(...values) {
  for (const value of values) {
    const v = clean(value, 500);
    if (v) return v;
  }
  return '';
}

function osmId(type, id) {
  if (!type || !id) return '';
  const t = String(type).toUpperCase();
  return /^[NWR]$/.test(t) ? `${t}${id}` : '';
}

function scoreProspect(p, keywords) {
  const hay = `${p.name} ${p.address}`.toLowerCase();
  let score = 42;
  if (p.website) score += 24;
  if (p.phone) score += 12;
  if (p.email) score += 8;
  if (p.address) score += 5;
  if (keywords.some(k => hay.includes(k))) score += 8;
  return Math.min(97, score);
}

function normalizePhoton(features, country, keywords) {
  const seen = new Set();
  const out = [];
  for (const feature of features || []) {
    const p = feature?.properties || {};
    const extra = p.extra || {};
    const coords = feature?.geometry?.coordinates || [];
    const name = firstValue(p.name, extra.name);
    if (!name || coords.length < 2) continue;
    const lon = Number(coords[0]);
    const lat = Number(coords[1]);
    if (!Number.isFinite(lat) || !Number.isFinite(lon)) continue;
    const key = `${name.toLowerCase()}|${Math.round(lat * 10000)}|${Math.round(lon * 10000)}`;
    if (seen.has(key)) continue;
    seen.add(key);
    const address = [p.housenumber || extra.housenumber, p.street || extra.street, p.city || extra.city, p.state || extra.state, p.postcode || extra.postcode].filter(Boolean).join(' ');
    const website = firstValue(p.website, p.url, p['contact:website'], extra.website, extra.url, extra['contact:website']);
    const phone = firstValue(p.phone, p['contact:phone'], extra.phone, extra['contact:phone']);
    const email = firstValue(p.email, p['contact:email'], extra.email, extra['contact:email']);
    const socials = [p.facebook, p.instagram, p.linkedin, p.twitter, extra.facebook, extra.instagram, extra.linkedin, extra.twitter].filter(Boolean);
    const item = {
      name,
      website,
      phone,
      email,
      socials,
      address: address || country,
      latitude: lat,
      longitude: lon,
      osmId: osmId(p.osm_type, p.osm_id),
      source: 'OpenStreetMap / Photon',
      score: 0,
      evidence: []
    };
    item.score = scoreProspect(item, keywords);
    item.evidence = [
      item.website ? 'Website listed in public map data' : 'Website not listed in map data',
      item.phone ? 'Phone listed in public map data' : 'Phone not listed in map data',
      item.email ? 'Email listed in public map data' : 'Email not listed in map data'
    ];
    out.push(item);
  }
  return out;
}

function mergeLookupData(items, lookup) {
  const byId = new Map();
  for (const r of lookup || []) byId.set(osmId(r.osm_type, r.osm_id), r);
  return items.map(item => {
    const r = byId.get(item.osmId);
    if (!r) return item;
    const tags = r.extratags || {};
    const a = r.address || {};
    const website = firstValue(item.website, tags.website, tags['contact:website'], tags.url);
    const phone = firstValue(item.phone, tags.phone, tags['contact:phone']);
    const email = firstValue(item.email, tags.email, tags['contact:email']);
    const address = firstValue(item.address !== 'United States' ? item.address : '', [a.house_number, a.road, a.city || a.town || a.village, a.state, a.postcode].filter(Boolean).join(' '), item.address);
    const merged = { ...item, website, phone, email, address };
    merged.score = scoreProspect(merged, []);
    merged.evidence = [
      website ? 'Website verified in OSM tags' : 'No public website found in OSM tags',
      phone ? 'Phone verified in OSM tags' : 'No public phone found in OSM tags',
      email ? 'Email verified in OSM tags' : 'No public email found in OSM tags'
    ];
    return merged;
  });
}

function inspectText(text, website) {
  const source = String(text || '');
  const lower = source.toLowerCase();
  const hasForm = /(<form\b|contact form|submit)/i.test(source);
  const hasPhone = /\+?\d[\d\s().-]{7,}/.test(source);
  const hasEmail = /[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}/i.test(source);
  const hasChat = /(intercom|drift|tidio|hubspot|zendesk|crisp|livechat|tawk\.to|chatbot|ai assistant|virtual assistant)/i.test(lower);
  const hasCTA = /(book|schedule|request|contact|consultation|get started|call us|enquire|inquire|appointment|valuation|let's talk|talk to)/i.test(lower);
  const hasQualification = /(budget|price range|timeline|requirements|property type|location|preferred|when are you looking|how can we help|tell us about)/i.test(lower);
  const weaknesses = [];
  if (!hasForm) weaknesses.push('No obvious lead form detected');
  if (!hasCTA) weaknesses.push('No strong conversion CTA detected');
  if (!hasChat) weaknesses.push('No obvious AI/live-chat concierge detected');
  if (!hasQualification) weaknesses.push('No obvious qualification questions detected');
  if (!hasPhone && !hasEmail) weaknesses.push('No obvious direct contact signal detected');
  const evidence = [];
  if (hasForm) evidence.push('Lead form detected');
  if (hasCTA) evidence.push('Conversion CTA detected');
  if (hasChat) evidence.push('Chat/AI technology signal detected');
  if (hasQualification) evidence.push('Qualification language detected');
  return {
    status: 'inspected', url: website,
    signals: { hasForm, hasCTA, hasChat, hasQualification, hasPhone, hasEmail, textLength: source.length },
    weaknesses, evidence
  };
}

async function inspectWebsite(website) {
  const url = website.startsWith('http') ? website : `https://${website}`;
  try {
    const r = await fetch(`https://r.jina.ai/${url}`, { headers: { accept: 'text/plain', 'user-agent': 'LeadFlowAutomation-ProspectResearch/1.1' } });
    if (!r.ok) return { ok: false, reason: `Website reader returned HTTP ${r.status}.` };
    const text = await r.text();
    return { ok: true, ...inspectText(text, url) };
  } catch (error) {
    return { ok: false, reason: String(error?.message || error) };
  }
}

async function photonSearch(location, lat, lon, industry, tags, country) {
  const queries = industry === 'real estate'
    ? ['real estate', 'real estate agency', 'property management', 'realtor', 'realty']
    : [industry];
  const jobs = [];
  for (const q of queries) {
    for (const tag of tags) {
      const url = `https://photon.komoot.io/api/?q=${encodeURIComponent(`${q} ${location}`)}&lat=${lat}&lon=${lon}&zoom=12&limit=100&osm_tag=${encodeURIComponent(tag.replace('=', ':'))}`;
      jobs.push(fetch(url, { headers: { accept: 'application/json', 'user-agent': 'LeadFlowAutomation-ProspectResearch/1.1' } }).then(async r => r.ok ? r.json() : null).catch(() => null));
    }
  }
  const responses = await Promise.all(jobs);
  const keywords = INDUSTRY_KEYWORDS[industry] || [industry];
  const all = responses.flatMap(r => normalizePhoton(r?.features || [], country, keywords));
  const unique = new Map();
  for (const p of all) {
    const key = `${p.name.toLowerCase()}|${Math.round(p.latitude * 1000)}|${Math.round(p.longitude * 1000)}`;
    if (!unique.has(key) || p.score > unique.get(key).score) unique.set(key, p);
  }
  return [...unique.values()].sort((a, b) => b.score - a.score);
}

async function lookupOsm(items, country) {
  const ids = items.map(x => x.osmId).filter(Boolean);
  if (!ids.length) return items;
  const merged = [];
  for (let i = 0; i < ids.length; i += 50) {
    const batch = ids.slice(i, i + 50);
    const url = `https://nominatim.openstreetmap.org/lookup?format=jsonv2&osm_ids=${encodeURIComponent(batch.join(','))}&addressdetails=1&extratags=1&namedetails=1`;
    try {
      const r = await fetch(url, { headers: { accept: 'application/json', 'user-agent': 'LeadFlowAutomation-ProspectResearch/1.1 (+https://leadflowautomations.github.io/)' } });
      if (r.ok) merged.push(...await r.json());
    } catch (error) { console.error('osm_lookup_failed', error); }
  }
  return mergeLookupData(items, merged).map(x => ({ ...x, address: x.address || country }));
}

async function prospectSearch(request, origin) {
  const u = new URL(request.url);
  const location = clean(u.searchParams.get('location'), 120);
  const country = clean(u.searchParams.get('country'), 120);
  const industry = clean(u.searchParams.get('industry'), 120).toLowerCase();
  const limit = Math.min(100, Math.max(10, Number(u.searchParams.get('limit') || 100)));
  if (!location || !country || !industry) return json({ error: 'location, country and industry are required.' }, 400, origin);

  const geoUrl = `https://nominatim.openstreetmap.org/search?format=jsonv2&limit=1&q=${encodeURIComponent(`${location}, ${country}`)}`;
  let geo;
  try {
    const r = await fetch(geoUrl, { headers: { accept: 'application/json', 'user-agent': 'LeadFlowAutomation-ProspectResearch/1.1 (+https://leadflowautomations.github.io/)' } });
    if (!r.ok) return json({ error: `Location provider returned HTTP ${r.status}.` }, 502, origin);
    geo = await r.json();
  } catch (error) {
    return json({ error: 'Location provider could not be reached.', detail: String(error?.message || error) }, 502, origin);
  }
  if (!geo?.[0]) return json({ error: `Could not locate ${location}, ${country}.` }, 404, origin);
  const lat = Number(geo[0].lat), lon = Number(geo[0].lon);
  const tags = INDUSTRY_TAGS[industry] || [];
  if (!tags.length) return json({ error: `Industry "${industry}" is not supported yet.` }, 400, origin);

  let prospects = await photonSearch(location, lat, lon, industry, tags, country);
  if (!prospects.length) return json({ error: 'No matching public business records were returned. Try a broader area or industry.' }, 404, origin);

  prospects = await lookupOsm(prospects.slice(0, Math.min(100, prospects.length)), country);
  prospects.sort((a, b) => (b.score || 0) - (a.score || 0));
  const inspectCount = Math.min(12, prospects.length);
  const inspected = await Promise.all(prospects.slice(0, inspectCount).map(async p => {
    if (!p.website) return { ...p, verified: false, confidence: 'Low', tier: 'Needs research', recommendation: 'No public website was found in the map data. Validate before outreach.', weaknesses: ['No public website found'] };
    const inspection = await inspectWebsite(p.website);
    if (!inspection.ok) return { ...p, verified: false, confidence: 'Medium', tier: 'Needs validation', recommendation: 'Website found but could not be independently inspected.', weaknesses: ['Website could not be independently inspected'], inspection: { status: 'failed', reason: inspection.reason, url: p.website } };
    const score = Math.min(97, Math.round((p.score || 50) * 0.65 + (inspection.weaknesses.length ? 62 : 78) * 0.35));
    return { ...p, score, verified: true, confidence: inspection.evidence.length >= 3 ? 'High' : 'Medium', tier: score >= 80 ? 'Priority target' : score >= 65 ? 'Strong prospect' : 'Worth validating', recommendation: score >= 80 ? 'Research decision-maker and prepare personalized outreach' : 'Validate the enquiry journey and prepare a tailored angle', weaknesses: inspection.weaknesses, evidence: [...p.evidence, ...inspection.evidence], inspection };
  }));
  const byKey = new Map(inspected.map(p => [`${p.name.toLowerCase()}|${Math.round(p.latitude * 1000)}|${Math.round(p.longitude * 1000)}`, p]));
  prospects = prospects.map(p => byKey.get(`${p.name.toLowerCase()}|${Math.round(p.latitude * 1000)}|${Math.round(p.longitude * 1000)}`) || p);
  prospects.sort((a, b) => (b.score || 0) - (a.score || 0));

  return json({ ok: true, version: VERSION, query: { location, country, industry }, center: { latitude: lat, longitude: lon }, count: prospects.length, researched: inspectCount, provider: 'Photon + Nominatim OSM enrichment + website inspection', prospects: prospects.slice(0, limit) }, 200, origin);
}

export default {
  async fetch(request) {
    const origin = request.headers.get('Origin') || DEFAULT_ORIGIN;
    if (request.method === 'OPTIONS') return new Response(null, { status: 204, headers: cors(origin) });
    const url = new URL(request.url);
    try {
      if (request.method === 'GET' && url.pathname === '/api/health') return json({ ok: true, service: 'leadflow-prospect-intelligence', version: VERSION }, 200, origin);
      if (request.method === 'GET' && url.pathname === '/api/prospect-search') return await prospectSearch(request, origin);
      return json({ error: 'Not found.' }, 404, origin);
    } catch (error) {
      console.error('prospect_worker_error', error);
      return json({ error: 'Prospect research failed.', detail: String(error?.message || error) }, 500, origin);
    }
  }
};
