import step5 from './entry-step5.js';
import { verifyProspects } from './prospect-verification.js';

const ALLOWED=new Set(['https://leadflowautomations.github.io','https://leadflowautomations-github-io.pages.dev']);
const cors=origin=>({'Access-Control-Allow-Origin':ALLOWED.has(origin)?origin:'https://leadflowautomations.github.io','Access-Control-Allow-Methods':'GET, POST, OPTIONS','Access-Control-Allow-Headers':'Content-Type, Authorization, Accept','Access-Control-Max-Age':'86400','Vary':'Origin'});
const json=(data,status=200,origin='https://leadflowautomations.github.io')=>new Response(JSON.stringify(data),{status,headers:{'content-type':'application/json; charset=utf-8','cache-control':'no-store',...cors(origin)}});

export default{async fetch(request,env,ctx){
  const url=new URL(request.url),origin=request.headers.get('Origin')||'https://leadflowautomations.github.io';
  if(request.method==='OPTIONS')return new Response(null,{status:204,headers:cors(origin)});
  if(url.pathname==='/api/prospect-verify'){
    if(request.method!=='POST')return json({ok:false,error:'Method not allowed'},405,origin);
    try{
      const body=await request.json(),prospects=Array.isArray(body?.prospects)?body.prospects:[],industry=String(body?.industry||'').trim();
      if(!prospects.length)return json({ok:false,error:'prospects are required.'},400,origin);
      if(prospects.length>100)return json({ok:false,error:'A maximum of 100 prospects can be verified at once.'},400,origin);
      if(!industry)return json({ok:false,error:'industry is required.'},400,origin);
      const output=await verifyProspects(prospects,industry);
      return json({ok:true,stage:'verify',version:'2026-09-06.1',industry,summary:{verified:output.filter(p=>p.verification?.verified).length,needsReview:output.filter(p=>!p.verification?.verified&&!p.verification?.duplicateOf).length,duplicates:output.filter(p=>p.verification?.duplicateOf).length},prospects:output},200,origin);
    }catch(error){return json({ok:false,error:error?.message||'Verification failed.'},500,origin);}
  }
  return step5.fetch(request,env,ctx);
}};
