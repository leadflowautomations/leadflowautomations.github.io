import base from './entry-step5-verify.js';

const ORIGIN='https://leadflowautomations.github.io';
const ALLOWED=new Set([ORIGIN,'https://leadflowautomations-github-io.pages.dev']);
const cors=o=>({'Access-Control-Allow-Origin':ALLOWED.has(o)?o:ORIGIN,'Access-Control-Allow-Methods':'GET, POST, OPTIONS','Access-Control-Allow-Headers':'Content-Type, Authorization, Accept','Cache-Control':'no-store','Vary':'Origin'});
const json=(x,s=200,o=ORIGIN)=>new Response(JSON.stringify(x),{status:s,headers:{'content-type':'application/json; charset=utf-8',...cors(o)}});
const text=v=>String(v??'').trim();

const DISCOVERY_TAGS={
  'real estate':['office:estate_agent','office:property_management','shop:estate_agent'],
  'real estate agency':['office:estate_agent','office:property_management','shop:estate_agent'],
  realtor:['office:estate_agent','shop:estate_agent'],
  property:['office:estate_agent','office:property_management','shop:estate_agent'],
  restaurant:['amenity:restaurant'],restaurants:['amenity:restaurant'],
  hotel:['tourism:hotel'],hotels:['tourism:hotel'],
  dentist:['amenity:dentist'],dental:['amenity:dentist'],
  'law firm':['office:lawyer'],law:['office:lawyer'],lawyers:['office:lawyer'],
  accounting:['office:accountant'],accountant:['office:accountant'],
  fitness:['leisure:fitness_centre'],gym:['leisure:fitness_centre'],
  beauty:['shop:beauty','shop:hairdresser'],salon:['shop:hairdresser'],
  'car dealer':['shop:car'],automotive:['shop:car','shop:car_repair'],
  pharmacy:['amenity:pharmacy'],cafe:['amenity:cafe'],school:['amenity:school'],
  clinic:['amenity:clinic'],medical:['amenity:clinic','amenity:doctors']
};

function photonValue(p,...keys){for(const key of keys){const v=p?.[key]??p?.extra?.[key];if(text(v))return text(v)}return '';}
function photonAddress(p,country){return [p?.housenumber,p?.street,p?.district,p?.city,p?.state,p?.postcode].filter(Boolean).join(' ')||text(country);}
function normalizePhoton(features,country){
  const seen=new Set(),out=[];
  for(const f of features||[]){
    const p=f?.properties||{},coords=f?.geometry?.coordinates||[];
    const lon=Number(coords[0]),lat=Number(coords[1]),name=text(p.name);
    if(!name||!Number.isFinite(lat)||!Number.isFinite(lon))continue;
    const key=`${name.toLowerCase()}|${Math.round(lat*1000)}|${Math.round(lon*1000)}`;
    if(seen.has(key))continue;seen.add(key);
    const website=photonValue(p,'website','contact:website','url');
    const phone=photonValue(p,'phone','contact:phone');
    const email=photonValue(p,'email','contact:email');
    out.push({name,website,phone,email,socials:[],address:photonAddress(p,country),latitude:lat,longitude:lon,source:'Photon/OpenStreetMap',evidence:[website?'Public website listed':'No public website listed',phone?'Public phone listed':'No public phone listed',email?'Public email listed':'No public email listed','Discovery recovered from Photon/OpenStreetMap.']});
  }
  return out;
}

async function photonFallback(location,country,industry){
  const tags=DISCOVERY_TAGS[text(industry).toLowerCase()];
  if(!tags?.length)throw new Error('Photon fallback does not support this industry yet.');
  const geo=await fetch(`https://nominatim.openstreetmap.org/search?format=jsonv2&limit=1&q=${encodeURIComponent(`${location}, ${country}`)}`,{headers:{accept:'application/json','user-agent':'LeadFlowAutomation/1.0 (+https://leadflowautomations.github.io)'}});
  if(!geo.ok)throw new Error(`Location lookup failed (HTTP ${geo.status}).`);
  const places=await geo.json();
  if(!places?.[0])throw new Error(`Could not locate ${location}, ${country}.`);
  const lat=Number(places[0].lat),lon=Number(places[0].lon);
  const results=await Promise.all(tags.map(async tag=>{
    const url=new URL('https://photon.komoot.io/reverse');
    url.searchParams.set('lat',String(lat));url.searchParams.set('lon',String(lon));url.searchParams.set('radius','20');url.searchParams.set('limit','50');url.searchParams.set('distance_sort','true');url.searchParams.set('osm_tag',tag);
    const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),12000);
    try{const r=await fetch(url,{headers:{accept:'application/json','user-agent':'LeadFlowAutomation/1.0 (+https://leadflowautomations.github.io)'},signal:controller.signal});if(!r.ok)throw new Error(`HTTP ${r.status}`);const d=await r.json();return Array.isArray(d?.features)?d.features:[];}finally{clearTimeout(timer);}
  }));
  const prospects=normalizePhoton(results.flat(),country).slice(0,1000);
  if(!prospects.length)throw new Error('Photon returned no matching businesses.');
  return {prospects,location,country,industry,center:{lat,lon},discoveryRadiusKm:20,discoveredCount:prospects.length,returnedCount:prospects.length,discoveryLimit:1000,source:'Photon/OpenStreetMap',discoveryProvider:'Photon',fallback:false,discoveryNote:'Used Photon/OpenStreetMap category search across a 20 km market radius.'};
}

function quality(p){
  const r=p?.research||{};
  if(r.status!=='inspected') return p;
  const signals=r.signals||{};
  const meaningful=Number(r.contentLength||0)>80||Boolean(r.title)||Boolean(r.description)||(Array.isArray(r.headings)&&r.headings.length>0)||Object.values(signals).some(Boolean);
  if(meaningful) return p;
  return {...p,research:{...r,status:p?.website?'website-found':'public-record-only',confidence:'medium',evidence:[...(r.evidence||[]),'Website response contained no usable page content; research downgraded.']}};
}
function qualityList(items){return Array.isArray(items)?items.map(quality):items;}

export default {async fetch(request,env,ctx){
  const url=new URL(request.url),origin=request.headers.get('Origin')||ORIGIN;
  if(request.method==='OPTIONS')return new Response(null,{status:204,headers:cors(origin)});
  if(request.method==='GET'&&url.pathname==='/api/prospect-search'){
    try{
      const d=await photonFallback(text(url.searchParams.get('location')),text(url.searchParams.get('country')),text(url.searchParams.get('industry')));
      return json({ok:true,stage:'discover',version:'2026-09-06.10',...d},200,origin);
    }catch(photonError){
      const primary=await base.fetch(request,env,ctx);
      if(primary.ok){try{const data=await primary.clone().json();if(Array.isArray(data?.prospects)&&data.prospects.length)return primary;}catch{}}
      if(primary.status>=400){try{const data=await primary.clone().json();return json({...data,error:`Photon discovery failed: ${photonError?.message||'failed'}. Primary Overpass discovery also failed: ${data?.error||'unknown error'}`},502,origin)}catch{}}
      return json({ok:false,error:photonError?.message||'Discovery failed.'},502,origin);
    }
  }
  if(request.method==='POST'&&url.pathname==='/api/prospect-score'){
    try{
      const body=await request.json();
      const next={...body,prospects:qualityList(body?.prospects||[])};
      return base.fetch(new Request(request,{body:JSON.stringify(next)}),env,ctx);
    }catch(e){return json({ok:false,error:e?.message||'Invalid scoring request.'},400,origin)}
  }
  if(request.method==='POST'&&url.pathname==='/api/prospect-signals'){
    const response=await base.fetch(request,env,ctx);
    if(!response.headers.get('content-type')?.includes('application/json'))return response;
    try{
      const data=await response.json();
      if(Array.isArray(data?.prospects))data.prospects=qualityList(data.prospects);
      return json(data,response.status,origin);
    }catch{return response}
  }
  return base.fetch(request,env,ctx);
}};
