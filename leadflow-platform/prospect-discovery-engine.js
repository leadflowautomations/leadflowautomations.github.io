/* Lead Flow Automation — Prospect Discovery Engine
 * Contract for: location + country + industry -> discover businesses -> normalize -> score -> rank.
 * A production research provider should return source-backed businesses; this engine never invents prospects.
 */
const DISCOVERY_ENGINE_VERSION = '0.1.0';

const DEFAULT_SCORING = {
  fit: 30,
  leadCaptureOpportunity: 20,
  responseOpportunity: 15,
  qualificationOpportunity: 15,
  personalizationOpportunity: 10,
  followUpOpportunity: 10
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

async function discoverAndRank(input, provider) {
  const query = buildDiscoveryQuery(input);
  if (typeof provider !== 'function') return { query, status: 'provider-not-connected', prospects: [], note: 'Connect a live business-search provider to discover real businesses and source-backed evidence.' };
  const raw = await provider(query);
  return { query, status: 'complete', prospects: rankProspects(raw || []) };
}

if (typeof window !== 'undefined') window.LeadFlowDiscovery = { DISCOVERY_ENGINE_VERSION, buildDiscoveryQuery, normalizeProspect, scoreProspect, rankProspects, discoverAndRank };
if (typeof module !== 'undefined') module.exports = { DISCOVERY_ENGINE_VERSION, buildDiscoveryQuery, normalizeProspect, scoreProspect, rankProspects, discoverAndRank };
