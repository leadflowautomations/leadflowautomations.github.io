const WORDS={
  'real estate':['real estate','realty','realtor','property','properties','homes','brokerage','estate agent','property management'],
  restaurant:['restaurant','kitchen','grill','eatery','bistro','dining'],
  hotel:['hotel','resort','inn','suites'],
  dentist:['dentist','dental'],
  'law firm':['law','attorney','legal'],
  accounting:['accounting','accountant','cpa'],
  fitness:['fitness','gym','training'],
  beauty:['beauty','salon','spa','hair'],
  'car dealer':['auto','motor','cars','dealer'],
  pharmacy:['pharmacy','chemist'],
  cafe:['cafe','coffee'],
  school:['school','academy'],
  clinic:['clinic','medical','health']
};
const clean=v=>String(v??'').trim();
const norm=v=>clean(v).toLowerCase().replace(/&/g,' and ').replace(/[^a-z0-9]+/g,' ').replace(/\s+/g,' ').trim();
const categoryMatch=(p,industry)=>{
  const i=norm(industry),words=WORDS[i]||[];
  if(!words.length)return {match:true,confidence:'medium',reason:'Industry is accepted by the discovery pipeline.'};
  const hay=norm([p?.name,p?.website,p?.address].filter(Boolean).join(' '));
  if(words.some(w=>hay.includes(norm(w))))return {match:true,confidence:'high',reason:`Business record contains ${industry}-relevant category evidence.`};
  if(String(p?.source||'').toLowerCase().includes('openstreetmap'))return {match:true,confidence:'medium',reason:'Business was returned from an industry-specific OpenStreetMap discovery tag.'};
  return {match:false,confidence:'medium',reason:`No clear ${industry} category evidence was found in the public record.`};
};
async function reachable(url){
  const site=clean(url);if(!site)return {checked:false,reachable:false,reason:'No website listed.'};
  const target=/^https?:\/\//i.test(site)?site:`https://${site}`;
  const controller=new AbortController();const timer=setTimeout(()=>controller.abort(),5500);
  try{let r=await fetch(target,{method:'HEAD',redirect:'follow',headers:{accept:'text/html,application/xhtml+xml','user-agent':'LeadFlowAutomation/1.0'},signal:controller.signal});if(!r.ok&&(r.status===405||r.status===403||r.status===400))r=await fetch(target,{method:'GET',redirect:'follow',headers:{accept:'text/html,application/xhtml+xml','range':'bytes=0-2048','user-agent':'LeadFlowAutomation/1.0'},signal:controller.signal});return {checked:true,reachable:r.ok,status:r.status,url:r.url||target,reason:r.ok?'Website responded successfully':`Website returned HTTP ${r.status}.`};}catch(error){return {checked:true,reachable:false,url:target,reason:error?.name==='AbortError'?'Website check timed out':'Website could not be reached.'};}finally{clearTimeout(timer);}
}
async function parallel(items,limit,fn){const out=new Array(items.length);let cursor=0;await Promise.all(Array.from({length:Math.min(limit,items.length)},async()=>{while(true){const i=cursor++;if(i>=items.length)return;out[i]=await fn(items[i],i);}}));return out;}
export async function verifyProspects(prospects,industry){
  // Verification validates identity/category and uniqueness first. Activity can be enriched later by public contact research.
  const list=Array.isArray(prospects)?prospects.slice(0,1000):[];
  const results=await parallel(list,8,async p=>{const website=await reachable(p?.website);const contact=Boolean(clean(p?.phone)||clean(p?.email));const active=website.reachable||contact;const activeConfidence=website.reachable?'high':contact?'medium':'low';const category=categoryMatch(p,industry);return {...p,__verification:{active,activeConfidence,category,website,contact}};});
  const seen=new Map();
  return results.map((p,index)=>{
    const nameKey=norm(p?.name),addressKey=norm(p?.address),lat=Number(p?.latitude),lon=Number(p?.longitude);let duplicateOf=null;
    for(const [key,prior] of seen){const sameName=nameKey&&key.startsWith(nameKey+'|');const sameAddress=addressKey&&prior.addressKey===addressKey;const near=Number.isFinite(lat)&&Number.isFinite(lon)&&Number.isFinite(prior.lat)&&Number.isFinite(prior.lon)&&Math.abs(lat-prior.lat)<0.0015&&Math.abs(lon-prior.lon)<0.0015&&nameKey===prior.nameKey;if(sameName&&(sameAddress||near)){duplicateOf=prior.index;break;}}
    if(nameKey)seen.set(`${nameKey}|${addressKey}`,{index:index+1,nameKey,addressKey,lat,lon});
    const v=p.__verification;delete p.__verification;const unique=!duplicateOf;const categoryFit=Boolean(v.category.match);const sourceBacked=/openstreetmap|photon/i.test(String(p?.source||''));
    // An industry-specific discovery source is enough to verify identity/category/uniqueness before research. Contact research separately confirms outreach activity.
    const verified=Boolean(unique&&categoryFit&&(v.active||sourceBacked));
    const status=duplicateOf?'duplicate':!unique?'duplicate':!categoryFit?'needs-review':verified?'verified':'needs-review';
    return {...p,verification:{verified,status,eligible:Boolean(unique&&categoryFit),active:v.active,activeConfidence:v.activeConfidence,categoryMatch:v.category.match,categoryConfidence:v.category.confidence,unique,duplicateOf,website:{checked:v.website.checked,reachable:v.website.reachable,status:v.website.status||null,reason:v.website.reason||'',url:v.website.url||p.website||''},evidence:[v.active?(v.website.reachable?'Website responded successfully':'Public phone/email signal found'):sourceBacked?'Industry-specific OpenStreetMap discovery record accepted; activity will be confirmed by contact research':'No active public signal found',v.category.reason,unique?'No duplicate match found':`Duplicate of result #${duplicateOf}`,categoryFit?'Category accepted for downstream research':'Category needs review']}};
  });
}
