import { researchProspects } from '../../../backend/prospect-signals.js';
import { scoreProspects } from '../../../backend/prospect-scoring.js';
import { rankProspects, summarizeRanking } from '../../../backend/prospect-ranking.js';

const ALLOWED = new Set(['https://leadflowautomations.github.io','https://leadflowautomations-github-io.pages.dev']);
const DEFAULT_ORIGIN = 'https://leadflowautomations.github.io';
const cors = origin => ({'Access-Control-Allow-Origin':ALLOWED.has(origin)?origin:DEFAULT_ORIGIN,'Access-Control-Allow-Methods':'GET, POST, OPTIONS','Access-Control-Allow-Headers':'Content-Type, Accept','Cache-Control':'no-store','Vary':'Origin'});
const json=(data,status=200,origin=DEFAULT_ORIGIN)=>new Response(JSON.stringify(data),{status,headers:{'content-type':'application/json; charset=utf-8',...cors(origin)}});

function buildSignals(p){
  const r=p.research||{},s=r.signals||{},website=Boolean(p.website),inspected=r.status==='inspected';
  const text=(r.title+' '+r.description+' '+(r.headings||[]).join(' ')).toLowerCase();
  const booking=Boolean(s.hasBooking||/book now|book online|schedule online|appointment|booking|reserve|reservation|calendly|acuity|setmore|simplybook|mindbody|square appointments|fresha/i.test(text));
  const reviews=Boolean(s.hasTestimonials||/review|reviews|testimonial|testimonials|client stories|google rating|rating/i.test(text)||s.rating);
  const social=(r.socials||[]).length>0;
  const seo=inspected?{title:Boolean(r.title),description:Boolean(r.description),headings:(r.headings||[]).length>0,contentLength:Number(r.contentLength||0),healthy:Boolean(r.title&&r.description&&(r.headings||[]).length>0)}:{title:false,description:false,headings:false,contentLength:0,healthy:false};
  const contact=Boolean((r.phones||[]).length||(r.emails||[]).length||p.phone||p.email);
  return {website:{present:website,reachable:inspected,status:inspected?'Inspected':website?'Found but not inspected':'Not found',https:website?/^https:/i.test(p.website):false,title:r.title||''},contact:{present:contact,summary:contact?'Direct contact signal found':'No direct contact signal found',phones:r.phones||[],emails:r.emails||[]},booking:{present:booking,summary:booking?'Booking/appointment signal detected':'No obvious booking system signal'},reviews:{present:reviews,summary:reviews?'Reviews/testimonial signal detected':'No obvious review/testimonial signal',rating:s.rating||''},social:{present:social,summary:social?`${r.socials.length} social profile link(s) detected`:'No social profile links detected',profiles:r.socials||[]},seo:{healthy:seo.healthy,summary:seo.healthy?'Basic title + description + headings detected':'Basic SEO signals are incomplete',...seo},technology:{chat:Boolean(s.hasChat),qualification:Boolean(s.hasQualification),form:Boolean(s.hasForm),analytics:Boolean(s.hasAnalytics)},evidence:r.evidence||[]};
}

async function prepare(prospects,context){
  const alreadyResearched=prospects.every(p=>p?.research?.status&&p?.signals?.website&&p?.signals?.technology);
  if(alreadyResearched)return prospects;
  const researched=await researchProspects(prospects,context);
  return researched.map(p=>({...p,signals:buildSignals(p),researchedAt:new Date().toISOString()}));
}

export default {async fetch(request){
  const url=new URL(request.url),origin=request.headers.get('Origin')||DEFAULT_ORIGIN;
  if(url.pathname==='/api/step4-health')return json({ok:true,stage:'step4-test',version:'2026-09-06.3'},200,origin);
  if(request.method==='OPTIONS')return new Response(null,{status:204,headers:cors(origin)});
  if(url.pathname!=='/api/prospect-signals'&&url.pathname!=='/api/prospect-score'&&url.pathname!=='/api/prospect-rank')return json({ok:false,error:'Not found'},404,origin);
  if(request.method!=='POST')return json({ok:false,error:'Method not allowed'},405,origin);
  try{
    const body=await request.json(),prospects=Array.isArray(body?.prospects)?body.prospects:[],location=String(body?.location||'').trim(),industry=String(body?.industry||'').trim().toLowerCase();
    if(!prospects.length)return json({ok:false,error:'prospects are required.'},400,origin);
    if(prospects.length>100)return json({ok:false,error:'A maximum of 100 prospects can be processed at once.'},400,origin);
    if(url.pathname==='/api/prospect-rank'){
      if(!prospects.every(p=>p?.score&&Number.isFinite(Number(p.score.score))))return json({ok:false,error:'Step 5 requires Step 4 scored prospects.'},400,origin);
      const ranked=rankProspects(prospects);
      return json({ok:true,stage:'rank',version:'2026-09-06.1',source:'step-4-score',location,industry,summary:summarizeRanking(ranked),prospects:ranked},200,origin);
    }
    const prepared=await prepare(prospects,{location,industry});
    if(url.pathname==='/api/prospect-signals')return json({ok:true,stage:'research-signals',version:'2026-09-06.3',location,industry,summary:{researched:prepared.length,inspected:prepared.filter(p=>p.research?.status==='inspected').length,websiteFound:prepared.filter(p=>p.research?.status==='website-found').length,publicRecordOnly:prepared.filter(p=>p.research?.status==='public-record-only').length},prospects:prepared},200,origin);
    const output=scoreProspects(prepared);
    return json({ok:true,stage:'score',version:'2026-09-06.3',source:'step-3-research-signals',location,industry,summary:{scored:output.length,veryHigh:output.filter(p=>p.score.opportunity==='Very high').length,high:output.filter(p=>p.score.opportunity==='High').length,moderate:output.filter(p=>p.score.opportunity==='Moderate').length,low:output.filter(p=>p.score.opportunity==='Low').length},prospects:output},200,origin);
  }catch(error){return json({ok:false,error:error?.message||'Step 4/5 test Worker failed.'},500,origin);}
}};
