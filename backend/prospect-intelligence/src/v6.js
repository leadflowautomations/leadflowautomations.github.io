import engine from './v4.js';

const ORIGIN='https://leadflowautomations.github.io';
const ALLOWED=new Set([ORIGIN,'https://leadflowautomations-github-io.pages.dev']);
const STOP=new Set(['the','and','of','for','a','an','inc','llc','ltd','limited','company','co','corporation','corp','group','real','estate','realty','realtor','brokerage','properties','property','homes','home','agency','services']);

function cors(origin){return {'content-type':'application/json; charset=utf-8','cache-control':'no-store','Access-Control-Allow-Origin':ALLOWED.has(origin)?origin:ORIGIN,'Access-Control-Allow-Methods':'GET, POST, OPTIONS','Access-Control-Allow-Headers':'Content-Type, Accept','Access-Control-Max-Age':'86400','Vary':'Origin'}};
function url(v){try{const u=new URL(String(v).trim());if(!/^https?:$/.test(u.protocol))return '';u.hash='';return u.href}catch{return ''}}
function tokens(name){return String(name||'').toLowerCase().replace(/&/g,' and ').split(/[^a-z0-9]+/).filter(x=>x.length>2&&!STOP.has(x))}
function guesses(name){const t=tokens(name);const raw=String(name||'').toLowerCase().replace(/&/g,' and ').replace(/[^a-z0-9 ]+/g,' ').split(/\s+/).filter(Boolean);const noIndustry=raw.filter(x=>!['real','estate','realty','realtor','brokerage','property','properties','homes','home','agency','services'].includes(x));const vals=[];const add=(s)=>{if(!s)return;const b=s.replace(/[^a-z0-9]/g,'');if(b.length<4)return;for(const host of [b+'.com','www.'+b+'.com']){const u='https://'+host;if(!vals.includes(u))vals.push(u)}};add(noIndustry.join(''));add(t.join(''));add(raw.slice(0,3).join(''));add(raw.slice(0,2).join(''));if(t.length>1)add(t.slice(0,2).join(''));return vals.slice(0,6)}
async function probe(candidate){const u=url(candidate);if(!u)return '';try{const r=await fetch(u,{redirect:'follow',headers:{accept:'text/html,application/xhtml+xml,text/plain;q=.8','user-agent':'LeadFlowAutomation-WebsiteVerifier/2026.09'}});const ct=(r.headers.get('content-type')||'').toLowerCase();if(r.ok&&(ct.includes('text/html')||ct.includes('application/xhtml+xml')||ct.includes('text/plain')))return r.url||u}catch{}return ''}
async function enrich(p){if(p?.website)return p;for(const g of guesses(p?.name||'')){const found=await probe(g);if(found)return {...p,website:found,websiteDiscovery:'Business-name domain candidate verified'}}return p}
export default {
 async fetch(request,env,ctx){
  const origin=request.headers.get('Origin')||ORIGIN;
  if(request.method==='OPTIONS')return new Response(null,{status:204,headers:cors(origin)});
  if(request.method!=='POST')return engine.fetch(request,env,ctx);
  try{
   const body=await request.json();
   const prospects=Array.isArray(body.prospects)?body.prospects:[];
   const enriched=[];for(const p of prospects)enriched.push(await enrich(p));
   const headers=new Headers(request.headers);headers.set('Content-Type','application/json');
   const rewritten=new Request(request,{body:JSON.stringify({...body,prospects:enriched}),headers});
   const response=await engine.fetch(rewritten,env,ctx);
   const out=new Headers(response.headers);for(const [k,v] of Object.entries(cors(origin)))out.set(k,v);
   return new Response(response.body,{status:response.status,statusText:response.statusText,headers:out});
  }catch(error){return new Response(JSON.stringify({ok:false,error:error?.message||'Prospect research failed'}),{status:500,headers:cors(origin)})}
 }
};