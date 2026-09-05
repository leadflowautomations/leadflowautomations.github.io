/* Lead Flow Automation — Prospect Discovery Engine
 * Live MVP provider: OpenStreetMap Nominatim + Overpass.
 * This discovers real mapped businesses without exposing an API key.
 * It is intentionally evidence-first: missing evidence stays missing.
 */
const DISCOVERY_ENGINE_VERSION = '0.2.0';

const DEFAULT_SCORING = {
  fit: 30,
  leadCaptureOpportunity: 20,
  responseOpportunity: 15,
  qualificationOpportunity: 15,
  personalizationOpportunity: 10,
  followUpOpportunity: 10
};

const INDUSTRY_TAGS = {
  'real estate': ['office=estate_agent', 'shop=estate_agent'],
  'real estate agency': ['office=estate_agent', 'shop=estate_agent'],
  'realtor': ['office=estate_agent', 'shop=estate_agent'],
  'property': ['office=estate_agent', 'shop=estate_agent'],
  'restaurant': ['amenity=restaurant'],
  'restaurants': ['amenity=restaurant'],
  'hotel': ['tourism=hotel'],
  'hotels': ['tourism=hotel'],
  'dentist': ['amenity=dentist'],
  'dental': ['amenity=dentist'],
  'law firm': ['office=lawyer'],
  'lawyers': ['office=lawyer'],
  'accounting': ['office=accountant'],
  'accountant': ['office=accountant'],
  'fitness': ['leisure=fitness_centre'],
  'gym': ['leisure=fitness_centre'],
  'beauty': ['shop=beauty', 'shop=hairdresser'],
  'salon': ['shop=hairdresser'],
  'car dealer': ['shop=car'],
  'automotive': ['shop=car', 'shop=car_repair'],
  'pharmacy': ['amenity=pharmacy'],
  'cafe': ['amenity=cafe'],
  'catering': ['amenity=restaurant', 'amenity=cafe'],
  'school': ['amenity=school'],
  'clinic': ['amenity=clinic'],
  'medical': ['amenity=clinic', 'amenity=doctors'],
  'real estate developer': ['office=estate_agent']
};

function buildDiscoveryQuery({ location, country, industry, radius = 'city' } = {}) {
  if (!location || !country || !industry) throw new Error('Location, country and industry are required.');
  return { location: location.trim(), country: country.trim(), industry: industry.trim(), radius };
}

function normalizeProspect(raw = {}) {
  return {
    id: String(raw.id || raw.placeId || '').trim(),
    name: String(raw.name || '').trim(),
    industry: String(raw.industry || '').trim(),
    location: String(raw.location || '').trim(),
    website: String(raw.website || '').trim(),
    source: String(raw.source || '').trim(),
    sourceUrl: String(raw.sourceUrl || '').trim(),
    evidence: Array.isArray(raw.evidence) ? raw.evidence : [],
    scores: raw.scores || {}
  };
}

function scoreProspect(prospect, scores = {}) {
  const weights = DEFAULT_SCORING;
  const values = Object.fromEntries(Object.keys(weights).map(k => [k, Math.max(0, Math.min(100, Number(scores[k] ?? prospect.scores?.[k] ?? 0)))]));
  const total = Object.keys(weights).reduce((sum, key) => sum + values[key] * weights[key], 0);
  const score = Math.round(total / 100);
  const tier = score >= 80 ? 'Priority target' : score >= 65 ? 'Strong prospect' : score >= 50 ? 'Worth validating' : 'Low priority';
  return { ...prospect, scores: values, score, tier };
}

function rankProspects(prospects = []) {
  return prospects.map(p => scoreProspect(normalizeProspect(p))).sort((a, b) => b.score - a.score).map((p, i) => ({ ...p, rank: i + 1 }));
}

function industryClauses(industry) {
  const key = industry.toLowerCase().trim();
  return INDUSTRY_TAGS[key] || ['office', 'shop', 'amenity', 'tourism'];
}

async function geocode(query) {
  const q = encodeURIComponent(`${query.location}, ${query.country}`);
  const response = await fetch(`https://nominatim.openstreetmap.org/search?format=jsonv2&limit=1&q=${q}`, { headers: { 'Accept': 'application/json' } });
  if (!response.ok) throw new Error('Location lookup failed. Please try again.');
  const places = await response.json();
  if (!places.length) throw new Error('Could not find that location. Try a city and country.');
  return { lat: Number(places[0].lat), lon: Number(places[0].lon), displayName: places[0].display_name };
}

function buildOverpassQuery(center, industry) {
  const clauses = industryClauses(industry).map(tag => {
    const [key, value] = tag.includes('=') ? tag.split('=') : [tag, null];
    return value
      ? `nwr["${key}"="${value}"](around:25000,${center.lat},${center.lon});`
      : `nwr["${key}"](around:25000,${center.lat},${center.lon});`;
  }).join('\n');
  return `[out:json][timeout:45];(${clauses});out center tags;`;
}

async function fetchOverpass(query) {
  const response = await fetch('https://overpass-api.de/api/interpreter', {
    method: 'POST',
    headers: { 'Content-Type': 'text/plain;charset=UTF-8', 'Accept': 'application/json' },
    body: query
  });
  if (!response.ok) throw new Error('Business discovery provider is busy. Please retry in a moment.');
  return response.json();
}

function parseOverpass(data, industry, country) {
  const seen = new Set();
  return (data.elements || []).map(el => {
    const t = el.tags || {};
    const lat = el.lat ?? el.center?.lat;
    const lon = el.lon ?? el.center?.lon;
    const name = String(t.name || '').trim();
    if (!name || lat == null || lon == null) return null;
    const id = `${el.type}/${el.id}`;
    if (seen.has(id)) return null;
    seen.add(id);
    const website = t.website || t['contact:website'] || '';
    const address = [t['addr:housenumber'], t['addr:street'], t['addr:city']].filter(Boolean).join(' ');
    const evidence = [{
      claim: `Mapped business identified as ${name}.`,
      source: 'OpenStreetMap',
      sourceUrl: `https://www.openstreetmap.org/${el.type}/${el.id}`,
      confidence: 0.9
    }];
    if (website) evidence.push({ claim: 'A public business website is listed.', source: 'OpenStreetMap', sourceUrl: `https://www.openstreetmap.org/${el.type}/${el.id}`, confidence: 0.95 });
    const scores = {
      fit: 85,
      leadCaptureOpportunity: website ? 45 : 65,
      responseOpportunity: 50,
      qualificationOpportunity: 55,
      personalizationOpportunity: 55,
      followUpOpportunity: 55
    };
    return normalizeProspect({ id, name, industry, location: address || country, website, source: 'OpenStreetMap', sourceUrl: `https://www.openstreetmap.org/${el.type}/${el.id}`, evidence, scores });
  }).filter(Boolean);
}

async function liveBusinessProvider(query) {
  const center = await geocode(query);
  const data = await fetchOverpass(buildOverpassQuery(center, query.industry));
  return parseOverpass(data, query.industry, query.country);
}

async function discoverAndRank(input, provider = liveBusinessProvider) {
  const query = buildDiscoveryQuery(input);
  const raw = await provider(query);
  const ranked = rankProspects(raw || []);
  return { query, status: 'complete', prospects: ranked, center: query.location };
}

if (typeof window !== 'undefined') window.LeadFlowDiscovery = { DISCOVERY_ENGINE_VERSION, buildDiscoveryQuery, normalizeProspect, scoreProspect, rankProspects, discoverAndRank, liveBusinessProvider };
if (typeof module !== 'undefined') module.exports = { DISCOVERY_ENGINE_VERSION, buildDiscoveryQuery, normalizeProspect, scoreProspect, rankProspects, discoverAndRank, liveBusinessProvider };
