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

const location='Miami, USA', industry='Real Estate';
console.log('Step 5 live validation: research real businesses with Step 3...');
const step3=await post('/api/prospect-signals',{prospects,location,industry});
if(step3.stage!=='research-signals'||step3.prospects.length!==prospects.length)throw new Error('Step 3 research validation failed.');

console.log('Step 5 live validation: score exact Step 3 output with Step 4...');
const step4=await post('/api/prospect-score',{prospects:step3.prospects,location,industry});
if(step4.stage!=='score'||step4.prospects.length!==prospects.length)throw new Error('Step 4 scoring validation failed.');
for(const p of step4.prospects){if(!p.score||typeof p.score.score!=='number'||p.score.score<0||p.score.score>100)throw new Error(`Invalid Step 4 score for ${p.name}`);}

console.log('Step 5 live validation: rank exact Step 4 output...');
const step5=await post('/api/prospect-rank',{prospects:step4.prospects,location,industry});
if(step5.stage!=='rank')throw new Error(`Unexpected Step 5 stage: ${step5.stage}`);
if(step5.source!=='step-4-score')throw new Error(`Unexpected Step 5 source: ${step5.source}`);
if(!/^2026-09-06\./.test(String(step5.version)))throw new Error(`Unexpected Step 5 version: ${step5.version}`);
if(!Array.isArray(step5.prospects)||step5.prospects.length!==prospects.length)throw new Error('Step 5 did not return all prospects.');
const scores=step5.prospects.map(p=>Number(p.score?.score));
for(let i=0;i<step5.prospects.length;i++){
  const p=step5.prospects[i];
  if(p.rank!==i+1)throw new Error(`Invalid rank for ${p.name}`);
  if(p.ranking?.rank!==i+1)throw new Error(`Invalid ranking metadata for ${p.name}`);
  if(i>0&&scores[i]>scores[i-1])throw new Error('Ranking is not sorted by Step 4 score descending.');
  if(Number(p.ranking?.score)!==scores[i])throw new Error(`Step 5 changed score for ${p.name}`);
}
console.log(JSON.stringify({stage:step5.stage,version:step5.version,summary:step5.summary,ranking:step5.prospects.map(p=>({rank:p.rank,name:p.name,score:p.score.score,opportunity:p.score.opportunity,priority:p.score.priority,confidence:p.score.confidence,topGaps:(p.score.gaps||[]).slice(0,3).map(g=>g.label)}))},null,2));
console.log('STEP5_LIVE_VALIDATION=PASS');
