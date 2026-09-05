/* Lead Flow Automation — live research adapter boundary
 * Keeps external research providers isolated from scoring/personalization.
 * Replace researchProvider() with an approved search/API integration in production.
 */
const LIVE_RESEARCH_VERSION = '0.1.0';

async function researchProvider({ name, website, industry, market }) {
  if (!name) throw new Error('Business name is required.');
  return {
    sourceStatus: 'provider-not-connected',
    business: { name, website: website || '', industry: industry || '', market: market || 'United States' },
    evidence: [],
    signals: [],
    note: 'No live claims are generated until a research provider returns source-backed evidence.'
  };
}

function normalizeEvidence(items = []) {
  return items.map((item, index) => ({
    id: item.id || `evidence-${index + 1}`,
    claim: String(item.claim || '').trim(),
    source: String(item.source || '').trim(),
    url: String(item.url || '').trim(),
    confidence: Math.max(0, Math.min(1, Number(item.confidence ?? 0)))
  })).filter(item => item.claim && item.source);
}

async function runLiveResearch(input) {
  const raw = await researchProvider(input);
  return { ...raw, evidence: normalizeEvidence(raw.evidence) };
}

if (typeof window !== 'undefined') window.LeadFlowLiveResearch = { LIVE_RESEARCH_VERSION, runLiveResearch, normalizeEvidence };
if (typeof module !== 'undefined') module.exports = { LIVE_RESEARCH_VERSION, runLiveResearch, normalizeEvidence };
