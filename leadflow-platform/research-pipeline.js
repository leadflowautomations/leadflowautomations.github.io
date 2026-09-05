/* Lead Flow Automation — reusable research pipeline contract
   Production adapter can replace the deterministic demo logic with live research/AI providers. */
const PIPELINE_VERSION = '0.1.0';

function analyzeBusiness(input = {}) {
  const name = (input.name || '').trim();
  const industry = (input.industry || 'Unknown').trim();
  const market = (input.market || 'United States').trim();
  const website = (input.website || '').trim();

  if (!name) throw new Error('Business name is required.');

  const signals = [
    { id: 'lead-capture', label: 'Lead capture', weight: 20, evidence: 'Assess forms, CTAs, chat and contact pathways.' },
    { id: 'response-speed', label: 'Response speed', weight: 20, evidence: 'Assess how quickly high-intent visitors can reach a human.' },
    { id: 'qualification', label: 'Qualification', weight: 20, evidence: 'Assess whether intent, budget, timeline and needs are captured.' },
    { id: 'personalization', label: 'Personalization', weight: 20, evidence: 'Assess whether the journey adapts to visitor intent.' },
    { id: 'follow-up', label: 'Follow-up', weight: 20, evidence: 'Assess continuity after an initial inquiry.' }
  ];

  return {
    pipelineVersion: PIPELINE_VERSION,
    business: { name, industry, market, website },
    signals,
    opportunity: {
      score: 0,
      status: 'Needs live research',
      primaryOpportunity: 'Connect live business evidence to the five lead-flow signals.',
      likelyBuyer: 'Owner, founder, growth lead, sales lead, or operations lead',
      friction: 'Not yet verified — research required before making a claim.',
      automationAngle: 'AI-assisted capture, qualification, routing and context-aware follow-up.',
      nextAction: 'Run live research, attach evidence to each signal, then calculate the score.'
    },
    personalizationBrief: {
      promise: `Turn ${name}'s existing customer journey into a more intelligent lead experience.`,
      experience: 'Adaptive AI concierge',
      handoff: 'Structured lead summary for the human team',
      proof: 'Interactive prospect-specific demo'
    }
  };
}

if (typeof window !== 'undefined') window.LeadFlowPipeline = { PIPELINE_VERSION, analyzeBusiness };
if (typeof module !== 'undefined') module.exports = { PIPELINE_VERSION, analyzeBusiness };
