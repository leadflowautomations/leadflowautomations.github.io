const base = process.env.TEST_WORKER_URL?.replace(/\/$/, '');
if (!base) throw new Error('TEST_WORKER_URL is required');

const prospects = [
  { name: 'The Keyes Company', website: 'https://www.keyes.com', address: 'Miami, FL, USA', phone: '', email: '' },
  { name: 'Brown Harris Stevens Miami', website: 'https://www.bhsmiami.com', address: 'Miami, FL, USA', phone: '', email: '' },
  { name: 'Douglas Elliman Real Estate', website: 'https://www.elliman.com', address: 'Miami, FL, USA', phone: '', email: '' }
];

async function post(path, body) {
  const response = await fetch(`${base}${path}`, { method: 'POST', headers: { 'content-type': 'application/json', accept: 'application/json' }, body: JSON.stringify(body) });
  const text = await response.text();
  let data;
  try { data = JSON.parse(text); } catch { throw new Error(`${path} returned non-JSON HTTP ${response.status}: ${text.slice(0, 500)}`); }
  if (!response.ok || !data.ok) throw new Error(`${path} failed HTTP ${response.status}: ${data.error || 'unknown error'}`);
  return data;
}

const location = 'Miami, USA';
const industry = 'Real Estate';
console.log('Step 4 validation: calling Step 3 research endpoint with real businesses...');
const step3 = await post('/api/prospect-signals', { prospects, location, industry });
if (step3.stage !== 'research-signals') throw new Error(`Unexpected Step 3 stage: ${step3.stage}`);
if (!Array.isArray(step3.prospects) || step3.prospects.length !== prospects.length) throw new Error('Step 3 did not return all test prospects.');
for (const p of step3.prospects) {
  if (!p.research?.status) throw new Error(`Missing research status for ${p.name}`);
  if (!p.signals?.website || !p.signals?.technology) throw new Error(`Missing normalized signals for ${p.name}`);
}
console.log(JSON.stringify({ stage: step3.stage, version: step3.version, summary: step3.summary, statuses: step3.prospects.map(p => ({ name: p.name, research: p.research?.status, website: p.website })) }, null, 2));

console.log('Step 4 validation: scoring the exact Step 3 output without re-running research...');
const step4 = await post('/api/prospect-score', { prospects: step3.prospects, location, industry });
if (step4.stage !== 'score') throw new Error(`Unexpected Step 4 stage: ${step4.stage}`);
if (!/^2026-09-06\./.test(String(step4.version))) throw new Error(`Unexpected Step 4 version: ${step4.version}`);
if (step4.source !== 'step-3-research-signals') throw new Error(`Unexpected Step 4 source: ${step4.source}`);
if (!Array.isArray(step4.prospects) || step4.prospects.length !== prospects.length) throw new Error('Step 4 did not return all scored prospects.');
for (const p of step4.prospects) {
  const score = p.score;
  if (!score || typeof score.score !== 'number') throw new Error(`Missing score for ${p.name}`);
  if (!['Very high', 'High', 'Moderate', 'Low'].includes(score.opportunity)) throw new Error(`Invalid opportunity tier for ${p.name}`);
  if (!['P1', 'P2', 'P3', 'P4'].includes(score.priority)) throw new Error(`Invalid priority for ${p.name}`);
  if (!['high', 'medium', 'low'].includes(score.confidence)) throw new Error(`Invalid confidence for ${p.name}`);
  if (!Array.isArray(score.gaps)) throw new Error(`Missing gap list for ${p.name}`);
  if (score.score < 0 || score.score > 100) throw new Error(`Score out of range for ${p.name}`);
}
console.log(JSON.stringify({ stage: step4.stage, version: step4.version, summary: step4.summary, results: step4.prospects.map(p => ({ name: p.name, score: p.score.score, opportunity: p.score.opportunity, priority: p.score.priority, confidence: p.score.confidence, topGaps: p.score.gaps.slice(0, 3).map(g => g.label) })) }, null, 2));
console.log('STEP4_LIVE_VALIDATION=PASS');
