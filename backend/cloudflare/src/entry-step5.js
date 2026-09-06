import app from './index.js';
import { researchProspects } from '../../../backend/prospect-signals.js';
import { scoreProspects } from '../../../backend/prospect-scoring.js';
import { rankProspects, summarizeRanking } from '../../../backend/prospect-ranking.js';

const ALLOWED = new Set(['https://leadflowautomations.github.io','https://leadflowautomations-github-io.pages.dev']);
const cors = origin => ({'Access-Control-Allow-Origin':ALLOWED.has(origin)?origin:'https://leadflowautomations.github.io','Access-Control-Allow-Methods':'GET, POST, OPTIONS','Access-Control-Allow-Headers':'Content-Type, Authorization, Accept','Access-Control-Max-Age':'86400','Vary':'Origin'});
const json = (data,status=200,origin='https://leadflowautomations.github.io') => new Response(JSON.stringify(data),{status,headers:{'content-type':'application/json; charset=utf-8','cache-control':'no-store',...cors(origin)}});
const text = v => String(v??'').trim();

const INDUSTRY_TAGS={
  'real estate':['office=estate_agent','office=property_management','shop=estate_agent'],
  'real estate agency':['office=estate_agent','office=property_management','shop=estate_agent'],
  realtor:['office=estate_agent','shop=estate_agent'],
  property:['office=estate_agent','office=property_management','shop=estate_agent'],
  restaurant:['amenity=restaurant'],restaurants:['amenity=restaurant'],
  hotel:['tourism=hotel'],hotels:['tourism=hotel'],
  dentist:['amenity=dentist'],dental:['amenity=dentist'],
  'law firm':['office=lawyer'],law:['office=lawyer'],lawyers:['office=lawyer'],
  accounting:['office=accountant'],accountant:['office=accountant'],
  fitness:['leisure=fitness_centre'],gym:['leisure=fitness_centre'],
  beauty:['shop=beauty','shop=hairdresser'],salon:['shop=hairdresser'],
  'car dealer':['shop=car'],automotive:['shop=car','shop=car_repair'],
  pharmacy:['amenity=pharmacy'],cafe:['amenity=cafe'],
  school:['amenity=school'],clinic:['amenity=clinic'],medical:['amenity=clinic','amenity=doctors']
};
const INDUSTRY_KEYWORDS={
  'real estate':['real estate','realty','realtor','properties','property','homes','brokerage'],
  'real estate agency':['real estate','realty','realtor','properties','property','homes','brokerage'],
  realtor:['realtor','realty','properties','homes'],property:['property','properties','realty','homes'],
  restaurant:['restaurant','kitchen','grill','eatery','bistro','dining'],hotel:['hotel','resort','inn','suites'],
  dentist:['dentist','dental'],dental:['dentist','dental'],'law firm':['law','attorney','legal'],lawyers:['law','attorney','legal'],
  accounting:['accounting','accountant','cpa'],fitness:['fitness','gym','training'],gym:['fitness','gym','training'],
  beauty:['beauty','salon','spa'],salon:['salon','hair'],'car dealer':['auto','motors','cars','dealer'],
  automotive:['auto','motors','cars','dealer'],pharmacy:['pharmacy','chemist'],cafe:['cafe','coffee'],
  school:['school','academy'],clinic:['clinic','medical','health'],medical:['clinic','medical','health']
};

function buildOverpassQuery(tags,lat,lon,radius){
  const clauses=tags.map(tag=>{const [key,value]=tag.split('=');return `nwr["${key}"="${value}"](around:${radius},${lat},${lon});`;}).join('');
  return `[out:json][timeout:45];(${clauses});out center tags;`;
}
function normalize(elements,country,industry){
  const seen=new Set(),keywords=INDUSTRY_KEYWORDS[industry.toLowerCase()]||[],items=[];
  for(const element of elements||[]){
    const tags=element.tags||{},name=text(tags.name),lat=element.lat??element.center?.lat,lon=element.lon??element.center?.lon;
    if(!name||lat==null||lon==null)continue;
    const hay=`${name} ${tags.description||''} ${tags['official_name']||''}`.toLowerCase();
    if(keywords.length&&!keywords.some(k=>hay.includes(k))&&industry.toLowerCase().includes('real estate')===false&&industry.toLowerCase()!=='realtor')continue;
    const key=`${name.toLowerCase()}|${Math.round(Number(lat)*1000)}|${Math.round(Number(lon)*1000)}`;
    if(seen.has(key))continue;seen.add(key);
    const website=text(tags.website||tags['contact:website']||tags.url),phone=text(tags.phone||tags['contact:phone']),email=text(tags.email||tags['contact:email']);
    const socials=[tags.facebook,tags.instagram,tags.linkedin,tags.twitter].filter(Boolean);
    const address=[tags['addr:housenumber'],tags['addr:street'],tags['addr:city'],tags['addr:state'],tags['addr:postcode']].filter(Boolean).join(' ');
    items.push({name,website,phone,email,socials,address:address||country,latitude:Number(lat),longitude:Number(lon),source:'OpenStreetMap',evidence:[website?'Public website listed':'No public website listed',phone?'Public phone listed':'No public phone listed',email?'Public email listed':'No public email listed']});
  }
  return items;
}
async function discover(location,country,industry,limit){
  const q=text(location),c=text(country),i=text(industry).toLowerCase(),tags=INDUSTRY_TAGS[i]||INDUSTRY_TAGS[Object.keys(INDUSTRY_TAGS).find(k=>i.includes(k))]||[];
  if(!tags.length)throw new Error(`Industry "${industry}" is not supported for automatic discovery yet.`);
  const geoUrl=`https://nominatim.openstreetmap.org/search?format=jsonv2&limit=1&q=${encodeURIComponent(`${q}, ${c}`)}`;
  const geoRes=await fetch(geoUrl,{headers:{accept:'application/json','user-agent':'LeadFlowAutomation/1.0'}});
  if(!geoRes.ok)throw new Error(`Location lookup failed (HTTP ${geoRes.status}).`);
  const geo=await geoRes.json();if(!geo?.[0])throw new Error(`Could not locate ${q}, ${c}.`);
  const lat=Number(geo[0].lat),lon=Number(geo[0].lon);
  const overpass=await fetch('https://overpass.kumi.systems/api/interpreter',{method:'POST',headers:{'content-type':'text/plain;charset=UTF-8'},body:buildOverpassQuery(tags,lat,lon,25000)});
  if(!overpass.ok)throw new Error(`Business discovery failed (HTTP ${overpass.status}).`);
  const data=await overpass.json();
  const prospects=normalize(data.elements,c,i).slice(0,Math.min(Math.max(Number(limit)||50,1),50));
  return {prospects,location:q,country:c,industry:text(industry),center:{lat,lon},source:'OpenStreetMap Overpass'};
}

function buildSignals(p){const r=p.research||{},s=r.signals||{},website=Boolean(p.website),inspected=r.status==='inspected';const textBlob=(r.title+' '+r.description+' '+(r.headings||[]).join(' ')).toLowerCase();const booking=Boolean(s.hasBooking||/book now|book online|schedule online|appointment|booking|reserve|reservation|calendly|acuity|setmore|simplybook|mindbody|square appointments|fresha/i.test(textBlob));const reviews=Boolean(s.hasTestimonials||/review|reviews|testimonial|testimonials|client stories|google rating|rating/i.test(textBlob)||s.rating);const social=(r.socials||[]).length>0;const seo=inspected?{title:Boolean(r.title),description:Boolean(r.description),headings:(r.headings||[]).length>0,contentLength:Number(r.contentLength||0),healthy:Boolean(r.title&&r.description&&(r.headings||[]).length>0)}:{title:false,description:false,headings:false,contentLength:0,healthy:false};const contact=Boolean((r.phones||[]).length||(r.emails||[]).length||p.phone||p.email);return {website:{present:website,reachable:inspected,status:inspected?'Inspected':website?'Found but not inspected':'Not found',https:website?/^https:/i.test(p.website):false,title:r.title||''},contact:{present:contact,summary:contact?'Direct contact signal found':'No direct contact signal found',phones:r.phones||[],emails:r.emails||[]},booking:{present:booking,summary:booking?'Booking/appointment signal detected':'No obvious booking system signal'},reviews:{present:reviews,summary:reviews?'Reviews/testimonial signal detected':'No obvious review/testimonial signal',rating:s.rating||''},social:{present:social,summary:social?`${r.socials.length} social profile link(s) detected`:'No social profile links detected',profiles:r.socials||[]},seo:{healthy:seo.healthy,summary:seo.healthy?'Basic title + description + headings detected':'Basic SEO signals are incomplete',...seo},technology:{chat:Boolean(s.hasChat),qualification:Boolean(s.hasQualification),form:Boolean(s.hasForm),analytics:Boolean(s.hasAnalytics)},evidence:r.evidence||[]};}
async function researchAndScore(prospects,{location='',industry=''}={}){const researched=await researchProspects(prospects,{location,industry});return scoreProspects(researched.map(p=>({...p,signals:buildSignals(p),researchedAt:new Date().toISOString()})));}

export default {async fetch(request,env,ctx){
  const url=new URL(request.url),origin=request.headers.get('Origin')||'https://leadflowautomations.github.io';
  if(request.method==='OPTIONS')return new Response(null,{status:204,headers:cors(origin)});
  if(url.pathname==='/api/prospect-search'){
    if(request.method!=='GET')return json({ok:false,error:'Method not allowed'},405,origin);
    try{const d=await discover(url.searchParams.get('location'),url.searchParams.get('country'),url.searchParams.get('industry'),url.searchParams.get('limit'));return json({ok:true,stage:'discover',version:'2026-09-06.1',...d},200,origin)}catch(error){return json({ok:false,error:error?.message||'Discovery failed.'},500,origin)}
  }
  if(url.pathname==='/api/prospect-rank'){
    if(request.method!=='POST')return json({ok:false,error:'Method not allowed'},405,origin);
    try{const body=await request.json(),prospects=Array.isArray(body?.prospects)?body.prospects:[],location=text(body?.location),industry=text(body?.industry).toLowerCase();if(!prospects.length)return json({ok:false,error:'prospects are required.'},400,origin);if(prospects.length>100)return json({ok:false,error:'A maximum of 100 prospects can be ranked at once.'},400,origin);if(!prospects.every(p=>p&&p.score&&Number.isFinite(Number(p.score.score))))return json({ok:false,error:'Step 5 requires Step 4 scored prospects. Run Step 4 first.'},400,origin);const ranked=rankProspects(prospects);return json({ok:true,stage:'rank',version:'2026-09-06.1',location,industry,source:'step-4-score',summary:summarizeRanking(ranked),prospects:ranked},200,origin)}catch(error){return json({ok:false,error:error?.message||'Ranking failed.'},500,origin)}
  }
  if(url.pathname==='/api/prospect-score'){
    if(request.method!=='POST')return json({ok:false,error:'Method not allowed'},405,origin);
    try{const body=await request.json(),prospects=Array.isArray(body?.prospects)?body.prospects:[],location=text(body?.location),industry=text(body?.industry).toLowerCase();if(!prospects.length)return json({ok:false,error:'prospects are required.'},400,origin);if(prospects.length>100)return json({ok:false,error:'A maximum of 100 prospects can be scored at once.'},400,origin);const output=await researchAndScore(prospects,{location,industry});return json({ok:true,stage:'score',version:'2026-09-06.3',location,industry,summary:{scored:output.length,veryHigh:output.filter(p=>p.score.opportunity==='Very high').length,high:output.filter(p=>p.score.opportunity==='High').length,moderate:output.filter(p=>p.score.opportunity==='Moderate').length,low:output.filter(p=>p.score.opportunity==='Low').length},prospects:output},200,origin)}catch(error){return json({ok:false,error:error?.message||'Scoring failed.'},500,origin)}
  }
  if(url.pathname==='/api/prospect-signals'){
    if(request.method!=='POST')return json({ok:false,error:'Method not allowed'},405,origin);
    try{const body=await request.json(),prospects=Array.isArray(body?.prospects)?body.prospects:[],location=text(body?.location),industry=text(body?.industry).toLowerCase();if(!prospects.length)return json({ok:false,error:'prospects are required.'},400,origin);if(prospects.length>100)return json({ok:false,error:'A maximum of 100 prospects can be researched at once.'},400,origin);const researched=await researchProspects(prospects,{location,industry}),output=researched.map(p=>({...p,signals:buildSignals(p),researchedAt:new Date().toISOString()}));return json({ok:true,stage:'research-signals',version:'2026-09-06.2',location,industry,summary:{researched:output.length,inspected:output.filter(p=>p.research?.status==='inspected').length,websiteFound:output.filter(p=>p.research?.status==='website-found').length,publicRecordOnly:output.filter(p=>p.research?.status==='public-record-only').length},prospects:output},200,origin)}catch(error){return json({ok:false,error:error?.message||'Signal research failed.'},500,origin)}
  }
  return app.fetch(request,env,ctx);
}};
