import app from './index.js';
import { researchProspects } from '../../../backend/prospect-signals.js';

const ALLOWED = new Set(['https://leadflowautomations.github.io','https://leadflowautomations-github-io.pages.dev']);
const cors = origin => ({'Access-Control-Allow-Origin':ALLOWED.has(origin)?origin:'https://leadflowautomations.github.io','Access-Control-Allow-Methods':'GET, POST, OPTIONS','Access-Control-Allow-Headers':'Content-Type, Authorization, Accept','Access-Control-Max-Age':'86400','Vary':'Origin'});
const json = (data,status=200,origin='https://leadflowautomations.github.io') => new Response(JSON.stringify(data),{status,headers:{'content-type':'application/json; charset=utf-8','cache-control':'no-store',...cors(origin)}});

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    const origin = request.headers.get('Origin') || 'https://leadflowautomations.github.io';
    if (url.pathname === '/api/prospect-signals') {
      if (request.method === 'OPTIONS') return new Response(null,{status:204,headers:cors(origin)});
      if (request.method !== 'POST') return json({ok:false,error:'Method not allowed'},405,origin);
      try {
        const body = await request.json();
        const prospects = Array.isArray(body?.prospects) ? body.prospects : [];
        const location = String(body?.location || '').trim();
        const industry = String(body?.industry || '').trim().toLowerCase();
        if (!prospects.length) return json({ok:false,error:'prospects are required.'},400,origin);
        if (prospects.length > 100) return json({ok:false,error:'A maximum of 100 prospects can be researched at once.'},400,origin);
        const researched = await researchProspects(prospects,{location,industry});
        const summary = {researched:researched.length,inspected:researched.filter(p=>p.research?.status==='inspected').length,websiteFound:researched.filter(p=>p.research?.status==='website-found').length,publicRecordOnly:researched.filter(p=>p.research?.status==='public-record-only').length};
        return json({ok:true,stage:'research-signals',version:'2026-09-06.1',location,industry,summary,prospects:researched},200,origin);
      } catch (error) {
        return json({ok:false,error:error?.message||'Signal research failed.'},500,origin);
      }
    }
    return app.fetch(request, env, ctx);
  }
};
