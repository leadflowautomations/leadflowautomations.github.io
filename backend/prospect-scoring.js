const bool=v=>v===true;

// Step 4 converts Step 3 evidence into an automation-opportunity score.
// Missing capability = opportunity; this is deliberately not a business-quality score.
export function scoreProspect(p={}){
  const s=p.signals||{}, t=s.technology||{}, w=s.website||{}, c=s.contact||{}, b=s.booking||{}, rv=s.reviews||{}, so=s.social||{}, seo=s.seo||{};
  const gaps=[];
  const add=(id,label,weight,missing,reason)=>{if(missing)gaps.push({id,label,weight,reason})};

  add('website','Website',18,!w.reachable,'No reachable website was verified.');
  add('contact','Direct contact',10,!c.present,'No direct phone/email signal was found.');
  add('booking','Booking / appointments',16,!b.present,'No obvious booking or appointment workflow was detected.');
  add('lead-form','Lead capture form',14,!bool(t.form),'No lead form was detected.');
  add('qualification','Lead qualification',12,!bool(t.qualification),'No obvious qualification questions were detected.');
  add('chat','AI / live chat',10,!bool(t.chat),'No obvious AI or live-chat capability was detected.');
  add('analytics','Analytics / measurement',8,!bool(t.analytics),'No obvious analytics or conversion measurement was detected.');
  add('seo','Basic SEO',7,!bool(seo.healthy),'Basic title, description, and heading signals are incomplete.');
  add('social','Social presence',3,!so.present,'No social profile links were detected from the researched website.');
  add('reviews','Reviews / testimonials',2,!rv.present,'No obvious review or testimonial signal was detected.');

  const max=100;
  let score=Math.round(gaps.reduce((n,g)=>n+g.weight,0)/max*100);

  // Evidence confidence prevents an unresearched record from looking like a strong lead.
  const status=p.research?.status||'';
  const confidence=status==='inspected'?'high':status==='website-found'?'medium':'low';
  if(confidence==='low')score=Math.round(score*0.45);
  else if(confidence==='medium')score=Math.round(score*0.75);

  const opportunity=score>=75?'Very high':score>=55?'High':score>=35?'Moderate':'Low';
  const priority=score>=75?'P1':score>=55?'P2':score>=35?'P3':'P4';
  const strengths=[];
  if(w.reachable)strengths.push('Reachable website');
  if(c.present)strengths.push('Direct contact');
  if(b.present)strengths.push('Booking workflow');
  if(bool(t.form))strengths.push('Lead form');
  if(bool(t.chat))strengths.push('Chat/AI');
  if(bool(t.analytics))strengths.push('Analytics');
  return {score,opportunity,priority,confidence,gaps:gaps.sort((a,b)=>b.weight-a.weight),strengths,rationale:gaps.length?`Primary opportunity: ${gaps.slice(0,3).map(g=>g.label).join(', ')}.`:'No material automation gaps were detected from the available evidence.',scoringVersion:'2026-09-06.1'};
}

export function scoreProspects(prospects=[]){return prospects.map(p=>({...p,score:scoreProspect(p)}));}
