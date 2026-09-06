import base from './entry-step5.js';

const ORIGIN='https://leadflowautomations.github.io';
const ALLOWED=new Set([ORIGIN,'https://leadflowautomations-github-io.pages.dev']);
const cors=o=>({'Access-Control-Allow-Origin':ALLOWED.has(o)?o:ORIGIN,'Access-Control-Allow-Methods':'GET, POST, OPTIONS','Access-Control-Allow-Headers':'Content-Type, Authorization, Accept','Cache-Control':'no-store','Vary':'Origin'});
const json=(x,s=200,o=ORIGIN)=>new Response(JSON.stringify(x),{status:s,headers:{'content-type':'application/json; charset=utf-8',...cors(o)}});

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
