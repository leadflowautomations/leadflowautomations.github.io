const clean=(v,n=3000)=>String(v??'').trim().slice(0,n);
const uniq=a=>[...new Set((a||[]).map(x=>clean(x,500)).filter(Boolean))];
const domain=v=>{try{return new URL(v).hostname.replace(/^www\./,'').toLowerCase()}catch{return ''}};
const badEmail=e=>/@(?:example|sentry|schema|wix|wordpress|domain)\./i.test(e);
const validUrl=v=>{try{const u=new URL(v);return /^https?:$/.test(u.protocol)?u.href:''}catch{return ''}};
const decode=v=>{try{if(v.includes('uddg='))return decodeURIComponent(new URL(v,'https://www.google.com').searchParams.get('uddg')||'')}catch{}return v};
const strip=v=>String(v||'').replace(/\s+/g,' ').trim();

function extract(text){
  const t=strip(text);
  const emails=uniq(t.match(/[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}/ig)||[]).filter(e=>!badEmail(e));
  const phones=uniq(t.match(/(?:\+?\d[\d\s().-]{7,}\d)/g)||[]).filter(p=>p.replace(/\D/g,'').length>=10);
  const urls=[];
  const re=/\[[^\]]+\]\((https?:\/\/[^)\s]+)\)/gi;let m;
  while((m=re.exec(t))&&urls.length<20){const u=validUrl(decode(m[1]));if(u&&domain(u)&&!urls.some(x=>domain(x)===domain(u)))urls.push(u)}
  return {emails,phones,urls};
}

async function jinaSearch(q){
  const targets=[
    `https://r.jina.ai/http://www.google.com/search?q=${encodeURIComponent(q)}`,
    `https://r.jina.ai/http://www.bing.com/search?q=${encodeURIComponent(q)}`
  ];
  for(const target of targets){
    try{
      const r=await fetch(target,{headers:{accept:'text/plain','user-agent':'LeadFlowContactResearch/1.0'}});
      if(!r.ok)continue;
      const text=await r.text();
      if(text&&text.length>100)return text;
    }catch{}
  }
  return '';
}

export async function enrichContacts(prospects,{location='',industry=''}={}){
  const list=Array.isArray(prospects)?prospects:[];
  const out=new Array(list.length);let cursor=0;
  const worker=async()=>{while(true){const i=cursor++;if(i>=list.length)return;const p=list[i];
    if(p?.phone&&p?.email){out[i]=p;continue;}
    const name=clean(p?.name,200);if(!name){out[i]=p;continue;}
    const q=`\"${name}\" \"${location}\" ${industry} contact email phone`;
    const text=await jinaSearch(q);const found=extract(text);
    const phones=uniq([p?.phone,...(p?.research?.phones||[]),...(p?.signals?.contact?.phones||[]),...found.phones]);
    const emails=uniq([p?.email,...(p?.research?.emails||[]),...(p?.signals?.contact?.emails||[]),...found.emails]);
    const sources=uniq([...(p?.research?.contactSources||[]),...found.urls]);
    out[i]={...p,phone:phones[0]||'',email:emails[0]||'',research:{...(p.research||{}),phones,emails,contactSources:sources,evidence:[...(p?.research?.evidence||[]),emails.length?'Public email contact found by search enrichment':'No additional public email found',phones.length?'Public phone contact found by search enrichment':'No additional public phone found']}};
  }};
  await Promise.all(Array.from({length:Math.min(5,list.length)},worker));
  return out;
}
