import asyncio, csv, io, re, time, uuid
from urllib.parse import urlparse
from typing import Any
import httpx
from bs4 import BeautifulSoup
from fastapi import BackgroundTasks, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

VERSION='leadflow-fastapi-v3.0.0-complete-pipeline'
UA='LeadFlow/3.0 (+https://leadflowautomations.github.io/)'
TIMEOUT=15.0
CONCURRENCY=6
NOMINATIM_DELAY=1.1
JOBS: dict[str,dict[str,Any]]={}
INDUSTRIES={
 'real estate':['real estate','realty','realtor','properties','property management','commercial real estate','residential real estate'],
 'law':['law firm','lawyer','attorney','legal services'],
 'dentist':['dentist','dental clinic','orthodontist'],
 'restaurant':['restaurant','cafe','bistro'],
 'salon':['hair salon','beauty salon','barber','salon'],
 'auto repair':['auto repair','car repair','mechanic','automotive repair'],
}
app=FastAPI(title='Lead Flow Complete Intelligence API',version=VERSION)
app.add_middleware(CORSMiddleware,allow_origins=['https://leadflowautomations.github.io','http://localhost:5500','http://127.0.0.1:5500'],allow_credentials=False,allow_methods=['GET','POST','OPTIONS'],allow_headers=['*'])

async def geo(c,city,country):
 r=await c.get('https://nominatim.openstreetmap.org/search',params={'q':f'{city}, {country}','format':'jsonv2','limit':1},headers={'User-Agent':UA}); r.raise_for_status(); a=r.json(); return (float(a[0]['lat']),float(a[0]['lon'])) if a else None

def toks(s): return set(re.findall(r'[a-z0-9]+',s.lower()))
def clean_url(v):
 if not v:return None
 v=v.strip(); v=v if re.match(r'https?://',v,re.I) else 'https://'+v
 try:
  u=urlparse(v)
  if not u.netloc or u.hostname in {'google.com','bing.com','duckduckgo.com'}:return None
  return v.rstrip('/')
 except:return None
def clean_email(v):
 if not v:return None
 v=v.strip().lower().replace('mailto:','').split('?')[0]
 return v if re.fullmatch(r"[a-z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-z0-9-]+(?:\.[a-z0-9-]+)+",v) else None
def clean_phone(v):
 if not v:return None
 d=re.sub(r'\D','',v)
 return v.strip() if 10<=len(d)<=15 and len(set(d))>1 else None

def match(name,text):
 a={x for x in toks(name) if len(x)>2}; b=toks(text)
 return bool(a) and len(a&b)>=max(1,min(2,len(a)))

def dedupe(rows):
 out={}
 for x in rows:
  k='|'.join(sorted(list(toks(x['name']))))+'|'+re.sub(r'[^a-z0-9]','',x.get('address','').lower())[:60]
  if k not in out: out[k]=x
  else:
   for f in ('website','phone','email','address'):
    if not out[k].get(f) and x.get(f):out[k][f]=x[f]
 return list(out.values())

async def nom_search(c,q,lat,lon,delta):
 await asyncio.sleep(NOMINATIM_DELAY)
 half=delta/2
 params={'q':q,'format':'jsonv2','limit':40,'viewbox':f'{lon-half},{lat+half},{lon+half},{lat-half}','bounded':1,'layer':'poi','addressdetails':1}
 r=await c.get('https://nominatim.openstreetmap.org/search',params=params,headers={'User-Agent':UA,'Referer':'https://leadflowautomations.github.io/'}); r.raise_for_status(); return r.json()

async def discover(city,industry,country,job):
 async with httpx.AsyncClient(timeout=TIMEOUT) as c:
  center=await geo(c,city,country)
  if not center:return []
  lat,lon=center; terms=INDUSTRIES.get(industry.lower().strip(),[industry]); rows=[]
  # 3x3 tiled search reduces local-result blind spots while keeping provider load controlled.
  delta=0.10 if abs(lat)>25 else 0.06
  jobs=[(q,lat+(iy-1)*delta,lon+(ix-1)*delta) for iy in range(3) for ix in range(3) for q in terms]
  job.update(stage='collect',message=f'Collecting candidates across {len(jobs)} local search windows…',collection_queries=len(jobs),updated_at=time.time())
  for n,(q,y,x) in enumerate(jobs,1):
   try:
    for r in await nom_search(c,q,y,x,delta):
     name=(r.get('name') or r.get('display_name','').split(',')[0]).strip()
     if not name:continue
     a=r.get('address') or {}
     rows.append({'source_id':'osm:'+str(r.get('osm_type'))+':'+str(r.get('osm_id')),'name':name,'address':', '.join(str(a[k]) for k in ('house_number','road','city','state','postcode') if a.get(k)) or r.get('display_name'),'lat':r.get('lat'),'lon':r.get('lon'),'website':clean_url((r.get('extratags') or {}).get('contact:website') or (r.get('extratags') or {}).get('website')),'phone':clean_phone((r.get('extratags') or {}).get('contact:phone') or (r.get('extratags') or {}).get('phone')),'email':clean_email((r.get('extratags') or {}).get('contact:email') or (r.get('extratags') or {}).get('email')),'source':'OpenStreetMap','industry':industry})
   except Exception as e: job['errors']+=1
   job.update(collection_completed=n,discovered=len(dedupe(rows)),updated_at=time.time())
  return dedupe(rows)

def emails(html): return list(dict.fromkeys(filter(None,[clean_email(x) for x in re.findall(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}',html)])))
def phones(html): return list(dict.fromkeys(filter(None,[clean_phone(x) for x in re.findall(r'(?:\+?\d[\d\s().-]{8,}\d)',BeautifulSoup(html,'html.parser').get_text(' '))])))

def site_signals(url,html,status,seconds,name):
 s=BeautifulSoup(html,'html.parser'); text=s.get_text(' ',strip=True); low=html.lower(); tl=text.lower(); scripts=' '.join(map(str,s.find_all('script'))).lower(); forms=s.find_all('form')
 title=s.title.get_text(' ',strip=True) if s.title else ''; desc=(s.find('meta',attrs={'name':re.compile('description',re.I)}) or {}).get('content','') if s.find('meta',attrs={'name':re.compile('description',re.I)}) else ''
 booking=any(x in low for x in ['calendly.com','acuityscheduling','book appointment','schedule appointment','book a consultation']); chat=any(x in low+scripts for x in ['intercom','tawk.to','crisp.chat','tidio','zendesk','livechat']); analytics=any(x in low+scripts for x in ['googletagmanager','google-analytics','gtag(','clarity.ms','hotjar']); social=any(x in low for x in ['facebook.com','instagram.com','linkedin.com','youtube.com','tiktok.com']); qualify=any(x in tl for x in ['budget','timeframe','property type','project type','service needed','preferred date','how can we help']); reviews=any(x in tl for x in ['reviews','testimonials','client stories','google reviews','yelp'])
 return {'website_exists':True,'website_working':status<400,'https':urlparse(url).scheme=='https','business_match':match(name,text),'lead_form':bool(forms),'booking':booking,'chatbot':chat,'analytics':analytics,'qualification':qualify,'seo':bool(title and desc and len(title)>=10),'social':social,'reviews':reviews,'slow':seconds>4,'status_code':status,'response_time':round(seconds,2),'title':title,'description':desc[:300],'emails_found':emails(html)[:10],'phones_found':phones(html)[:10]}

async def fetch(c,url):
 t=time.perf_counter()
 try:
  r=await c.get(url,follow_redirects=True,headers={'User-Agent':UA}); return r.status_code,str(r.url),r.text[:2000000],time.perf_counter()-t
 except:return 599,url,'',time.perf_counter()-t

async def contacts(c,website,name,home):
 pages=[home]+[website+'/'+p for p in ['contact','contact-us','about','about-us','get-in-touch']]; found=[]
 for u in pages:
  try:
   r=await c.get(u,follow_redirects=True,headers={'User-Agent':UA}); html=r.text[:1500000]
   if r.status_code>=400:continue
   text=BeautifulSoup(html,'html.parser').get_text(' ',strip=True)
   if not match(name,text):continue
   for e in emails(html):found.append(('email',e,str(r.url)))
   for p in phones(html):found.append(('phone',p,str(r.url)))
  except:pass
 return found

def verify_contact(item,found):
 domain=urlparse(item.get('website') or '').hostname or ''; domain=domain.lower().removeprefix('www.')
 ev=[]; email=item.get('email'); phone=item.get('phone')
 if email: ev.append('discovery email')
 if phone: ev.append('discovery phone')
 for typ,val,src in found:
  if typ=='email' and not email: email=val; ev.append('business website email')
  if typ=='phone' and not phone: phone=val; ev.append('business website phone')
 email_domain=(email.split('@')[-1].lower() if email and '@' in email else '')
 email_match=bool(domain and email_domain==domain)
 if email_match:ev.append('email domain matches website')
 return email,phone,{'email':bool(email),'phone':bool(phone),'email_domain_match':email_match,'website_source':any('business website' in x for x in ev),'evidence':ev}

def score(x,s):
 gaps=[]; points=0
 checks=[('website',not s.get('website_working'),18),('contact',not(x.get('phone') and x.get('email')),10),('booking',not s.get('booking'),16),('lead capture',not s.get('lead_form'),14),('qualification',not s.get('qualification'),12),('AI/live chat',not s.get('chatbot'),10),('analytics',not s.get('analytics'),8),('SEO',not s.get('seo'),7),('social',not s.get('social'),3),('reviews',not s.get('reviews'),2)]
 for label,bad,w in checks:
  if bad:points+=w;gaps.append(label)
 points=min(100,points); tier='Very High' if points>=75 else 'High' if points>=55 else 'Moderate' if points>=35 else 'Low'
 return points,tier,gaps

def automation(x):
 s=x.get('signals',{}); ready=bool(x.get('verified_business') and (x.get('phone') or x.get('email')))
 if x['score']>=75 and ready: action='PRIORITY_OUTREACH'
 elif x['score']>=55 and ready: action='OUTREACH'
 elif x['score']>=35: action='RESEARCH_MORE'
 else: action='NURTURE'
 return {'action':action,'outreach_ready':ready,'next_action':'Contact using verified public channel' if ready else 'Find an additional public contact source','reason':'High confirmed opportunity gaps with verified business identity' if ready and x['score']>=55 else 'Needs additional evidence before outreach'}

async def process(jobid,city,industry,country):
 j=JOBS[jobid]; started=time.perf_counter()
 try:
  j.update(status='discovering',stage='discover',message='Locating search area…',updated_at=time.time())
  rows=await discover(city,industry,country,j); j.update(candidate_count=len(rows),status='verifying',stage='verify',message=f'Collected {len(rows)} candidates. Verifying businesses and contacts…',updated_at=time.time())
  sem=asyncio.Semaphore(CONCURRENCY); results=[]
  async with httpx.AsyncClient(timeout=TIMEOUT) as c:
   async def one(x):
    async with sem:
     website=x.get('website'); signals={'website_exists':False,'website_working':False}; found=[]
     if website:
      st,final,html,sec=await fetch(c,website); signals=site_signals(final,html,st,sec,x['name']) if html else {'website_exists':True,'website_working':False,'business_match':False,'booking':False,'chatbot':False,'analytics':False,'qualification':False,'lead_form':False,'seo':False,'social':False,'reviews':False}
      if html and signals.get('business_match'): found=await contacts(c,final,x['name'],html)
     email,phone,cv=verify_contact(x,found); x.update(email=email,phone=phone,contact_verification=cv,signals=signals)
     x['verified_business']=bool(signals.get('business_match')) if website else bool(x.get('name') and x.get('address'))
     x['verification']={'identity':x['verified_business'],'website_business_match':bool(signals.get('business_match')),'source':'OpenStreetMap + business website' if website else 'OpenStreetMap','confidence':'high' if x['verified_business'] and (signals.get('business_match') or x.get('website')) else 'medium'}
     sc,tier,gaps=score(x,signals); x.update(score=sc,tier=tier,gaps=gaps,research_status='complete',automation=automation(x)); return x
   for start in range(0,len(rows),CONCURRENCY):
    batch=await asyncio.gather(*(one(x) for x in rows[start:start+CONCURRENCY]),return_exceptions=True)
    for r in batch:
     if isinstance(r,Exception):j['errors']+=1
     else:results.append(r)
    results.sort(key=lambda z:(z['score'],int(z['verification']['identity']),int(bool(z.get('email'))+bool(z.get('phone')))),reverse=True)
    for n,r in enumerate(results,1):r['rank']=n
    j.update(processed=len(results),results=results,message=f'Researched {len(results)} of {len(rows)} candidates…',updated_at=time.time())
  j.update(status='complete',stage='automate',message=f'Pipeline complete — {len(results)} businesses verified, researched, scored, ranked and actioned.',duration_seconds=round(time.perf_counter()-started,2),updated_at=time.time())
 except Exception as e:j.update(status='failed',stage='error',message='Pipeline failed',error=str(e)[:500],updated_at=time.time())

@app.get('/')
async def root():return {'service':'Lead Flow Complete Pipeline','version':VERSION,'pipeline':['discover','collect','verify','contact_verify','research','score','rank','automate'],'google_api_required':False}
@app.get('/health')
async def health():return {'status':'ok','version':VERSION,'active_jobs':sum(v['status'] not in ('complete','failed') for v in JOBS.values())}
@app.post('/research-jobs')
async def create(background_tasks:BackgroundTasks,city:str=Query(...),industry:str=Query(...),country:str=Query(...)):
 jid=str(uuid.uuid4()); JOBS[jid]={'job_id':jid,'city':city.strip(),'country':country.strip(),'industry':industry.strip(),'status':'queued','stage':'queued','message':'Queued','candidate_count':0,'processed':0,'errors':0,'results':[],'created_at':time.time(),'updated_at':time.time()}; background_tasks.add_task(process,jid,city.strip(),industry.strip(),country.strip()); return {'ok':True,'job_id':jid,'status':'queued','poll_url':'/research-jobs/'+jid}
@app.get('/research-jobs/{job_id}')
async def get(job_id):
 if job_id not in JOBS:raise HTTPException(404,'Research job not found')
 j=JOBS[job_id]; return j
@app.get('/research-jobs/{job_id}/automation')
async def automation_queue(job_id):
 if job_id not in JOBS:raise HTTPException(404,'Research job not found')
 r=JOBS[job_id].get('results',[]); return {'job_id':job_id,'queue':[x for x in r if x.get('automation',{}).get('outreach_ready')],'total_ready':sum(x.get('automation',{}).get('outreach_ready',False) for x in r)}
@app.get('/research-jobs/{job_id}/csv')
async def export(job_id):
 if job_id not in JOBS:raise HTTPException(404,'Research job not found')
 out=io.StringIO(); fields=['rank','name','address','website','phone','email','verified_business','score','tier','prospect_type','gaps','automation_action']; w=csv.DictWriter(out,fieldnames=fields);w.writeheader()
 for x in JOBS[job_id].get('results',[]):w.writerow({k:','.join(x.get(k,[])) if isinstance(x.get(k),list) else x.get(k,'') for k in fields})
 from fastapi.responses import PlainTextResponse
 return PlainTextResponse(out.getvalue(),media_type='text/csv',headers={'Content-Disposition':f'attachment; filename="leadflow-{job_id}.csv"'})
