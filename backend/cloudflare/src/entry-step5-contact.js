import base from './entry-step5-quality.js';
import { enrichContacts } from '../../../backend/prospect-contact-enrichment.js';

const ORIGIN='https://leadflowautomations.github.io';
const ALLOWED=new Set([ORIGIN,'https://leadflowautomations-github-io.pages.dev']);
const cors=o=>({'Access-Control-Allow-Origin':ALLOWED.has(o)?o:ORIGIN,'Access-Control-Allow-Methods':'GET, POST, OPTIONS','Access-Control-Allow-Headers':'Content-Type, Authorization, Accept','Cache-Control':'no-store','Vary':'Origin'});
const json=(x,s=200,o=ORIGIN)=>new Response(JSON.stringify(x),{status:s,headers:{'content-type':'application/json; charset=utf-8',...cors(o)}});
const text=v=>String(v??'').trim();

export default {async fetch(request,env,ctx){
  const url=new URL(request.url),origin=request.headers.get('Origin')||ORIGIN;
  if(request.method==='POST'&&url.pathname==='/api/prospect-signals'){
    const response=await base.fetch(request,env,ctx);
    if(!response.headers.get('content-type')?.includes('application/json'))return response;
    try{
      const data=await response.json();
      if(Array.isArray(data?.prospects)){
        const prospects=await enrichContacts(data.prospects,{location:text(data?.location),industry:text(data?.industry),browser:env?.BROWSER});
        data.prospects=prospects;
        data.summary={...(data.summary||{}),contactEnriched:prospects.filter(p=>p?.phone&&p?.email).length,phoneFound:prospects.filter(p=>p?.phone).length,emailFound:prospects.filter(p=>p?.email).length,browserContactResearch:Boolean(env?.BROWSER)};
      }
      return json(data,response.status,origin);
    }catch(e){return json({ok:false,error:e?.message||'Contact enrichment failed.'},500,origin)}
  }
  return base.fetch(request,env,ctx);
}};
