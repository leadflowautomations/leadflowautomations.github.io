/* Lead Flow Automation — Opportunity Scoring + Personalization Engine */
const OPPORTUNITY_ENGINE_VERSION = '0.1.0';

function scoreOpportunity(signals = []) {
  const items = signals.map(s => ({...s, score: Number.isFinite(s.score) ? Math.max(0, Math.min(100, s.score)) : 0}));
  const totalWeight = items.reduce((n, s) => n + (s.weight || 0), 0) || 1;
  const score = Math.round(items.reduce((n, s) => n + s.score * (s.weight || 0), 0) / totalWeight);
  const tier = score >= 80 ? 'High-value opportunity' : score >= 60 ? 'Promising opportunity' : score >= 40 ? 'Needs validation' : 'Low-confidence opportunity';
  return { score, tier, signals: items };
}

function buildPersonalizationBrief(business, opportunity) {
  const name = business?.name || 'This business';
  return {
    engineVersion: OPPORTUNITY_ENGINE_VERSION,
    business: business,
    opportunityScore: opportunity.score,
    opportunityTier: opportunity.tier,
    headline: `A more intelligent lead journey for ${name}.`,
    promise: 'Capture intent earlier, qualify naturally, and give the team better context before the handoff.',
    experience: {
      entry: 'Context-aware AI concierge',
      qualification: ['intent', 'need', 'budget', 'timeline', 'location or service preference'],
      output: 'Structured lead profile + recommended next action',
      handoff: 'Human-ready conversation summary'
    },
    demoBrief: {
      opening: `Welcome to ${name}. How can we help?`,
      behavior: 'Ask only the next most useful question based on the visitor response.',
      wowMoment: 'Reveal a concise personalized profile before handoff.',
      close: 'Offer a clear human next step without creating unnecessary friction.'
    }
  };
}

if (typeof window !== 'undefined') window.LeadFlowOpportunity = { OPPORTUNITY_ENGINE_VERSION, scoreOpportunity, buildPersonalizationBrief };
if (typeof module !== 'undefined') module.exports = { OPPORTUNITY_ENGINE_VERSION, scoreOpportunity, buildPersonalizationBrief };
