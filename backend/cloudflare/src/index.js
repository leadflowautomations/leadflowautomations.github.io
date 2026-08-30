const ALLOWED_ORIGIN = 'https://leadflowautomations.github.io';
const MODEL = '@cf/meta/llama-3.1-8b-instruct';

const BUSINESS_SPEC = `
You are LeadFlow Assistant for Lead Flow Automation, founded by David Elijah.
Business: AI chatbot development and lead-flow automation for small businesses.
Target clients: service businesses and other small businesses with 1–50 employees.
Packages: Starter $750, Professional $1,500, Premium $2,500.
Delivery: Starter 5 business days, Professional 7 days, Premium 10 days.
Optional maintenance: $200/month.
Starter: one chatbot, up to 20 FAQs, website embed, 1 revision.
Professional: Starter + advanced conversation flow, email/CRM integration, 2 revisions, 30 days minor tweaks.
Premium: Professional + multi-platform deployment, analytics dashboard, 3 revisions, 3 months maintenance, priority support.
Primary platform: website. Messenger, WhatsApp and Instagram may be added depending on requirements.
The chatbot can answer approved FAQs, capture leads after consent, qualify prospects and hand complex requests to a human.
Payment: 50% upfront and 50% on delivery.
Refund policy: if Lead Flow Automation cannot deliver as agreed, the upfront payment is refundable.
Contact: leadflowautomation.dav@gmail.com.
Never invent prices, timelines, capabilities, policies or integrations. If uncertain, say you need David to confirm.
`;

const cors = (origin) => ({
  'Access-Control-Allow-Origin': origin === ALLOWED_ORIGIN ? ALLOWED_ORIGIN : ALLOWED_ORIGIN,
  'Access-Control-Allow-Methods': 'GET,POST,OPTIONS',
  'Access-Control-Allow-Headers': 'Content-Type, Authorization',
  'Access-Control-Max-Age': '86400',
});

function json(data, status = 200, origin = ALLOWED_ORIGIN) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { 'content-type': 'application/json; charset=utf-8', ...cors(origin) },
  });
}

function clean(value, max = 2000) {
  if (value === null || value === undefined) return null;
  return String(value).trim().slice(0, max);
}

function validEmail(value) {
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value);
}

function conversationId() {
  return crypto.randomUUID();
}

function safeHistory(history) {
  if (!Array.isArray(history)) return [];
  return history.slice(-12).map(m => ({
    role: m?.role === 'assistant' ? 'assistant' : 'user',
    content: clean(m?.content, 1500) || '',
  })).filter(m => m.content);
}

async function chat(request, env, origin) {
  const body = await request.json();
  const message = clean(body.message, 1500);
  const history = safeHistory(body.history);
  const id = clean(body.conversationId, 100) || conversationId();
  if (!message) return json({ error: 'Message is required.' }, 400, origin);

  if (!env.AI) return json({ error: 'AI service is not configured yet.' }, 503, origin);

  const prompt = `${BUSINESS_SPEC}\n\nConversation:\n${history.map(m => `${m.role}: ${m.content}`).join('\n')}\nuser: ${message}\nassistant:`;
  const result = await env.AI.run(MODEL, {
    prompt,
    temperature: 0.2,
    max_tokens: 350,
  });
  const answer = clean(result?.response || result?.text, 3000) || 'I’m sorry, I could not answer that right now. Please contact David at leadflowautomation.dav@gmail.com.';

  if (env.DB) {
    await env.DB.prepare('INSERT INTO chat_logs (conversation_id, role, content) VALUES (?, ?, ?)').bind(id, 'user', message).run();
    await env.DB.prepare('INSERT INTO chat_logs (conversation_id, role, content) VALUES (?, ?, ?)').bind(id, 'assistant', answer).run();
  }

  return json({ conversationId: id, answer }, 200, origin);
}

async function createLead(request, env, origin) {
  const b = await request.json();
  const lead = {
    name: clean(b.name, 120),
    email: clean(b.email, 254),
    phone: clean(b.phone, 40),
    businessName: clean(b.businessName, 160),
    businessType: clean(b.businessType, 120),
    need: clean(b.need, 500),
    packageInterest: clean(b.packageInterest, 100),
    timeline: clean(b.timeline, 100),
    consent: b.consent === true,
    consentTimestamp: clean(b.consentTimestamp, 80),
    conversationId: clean(b.conversationId, 100) || conversationId(),
  };

  if (!lead.consent) return json({ error: 'Affirmative consent is required.' }, 400, origin);
  if (!lead.name || !validEmail(lead.email) || !lead.businessType || !lead.need || !lead.packageInterest || !lead.timeline || !lead.consentTimestamp) {
    return json({ error: 'Please provide all required lead details.' }, 400, origin);
  }
  if (!env.DB) return json({ error: 'Lead storage is not configured yet.' }, 503, origin);

  await env.DB.prepare(`INSERT INTO leads
    (conversation_id,name,email,phone,business_name,business_type,need,package_interest,timeline,consent,consent_timestamp)
    VALUES (?,?,?,?,?,?,?,?,?,?,?)`).bind(
      lead.conversationId, lead.name, lead.email, lead.phone, lead.businessName,
      lead.businessType, lead.need, lead.packageInterest, lead.timeline, 1, lead.consentTimestamp
    ).run();

  return json({ ok: true, conversationId: lead.conversationId }, 201, origin);
}

async function handoff(request, env, origin) {
  const b = await request.json();
  const name = clean(b.name, 120);
  const email = clean(b.email, 254);
  const transcript = clean(b.transcript, 12000);
  const reason = clean(b.reason, 500) || 'Human handoff requested';
  if (!name || !validEmail(email) || !transcript) return json({ error: 'Name, email and transcript are required.' }, 400, origin);

  let emailSent = false;
  if (env.RESEND_API_KEY && env.FROM_EMAIL) {
    const r = await fetch('https://api.resend.com/emails', {
      method: 'POST',
      headers: { Authorization: `Bearer ${env.RESEND_API_KEY}`, 'Content-Type': 'application/json' },
      body: JSON.stringify({
        from: env.FROM_EMAIL,
        to: ['leadflowautomation.dav@gmail.com'],
        reply_to: email,
        subject: `LeadFlow handoff: ${reason}`,
        text: `Lead: ${name} <${email}>\nReason: ${reason}\n\nTranscript:\n${transcript}`,
      }),
    });
    emailSent = r.ok;
  }

  return json({ ok: true, emailSent }, 200, origin);
}

export default {
  async fetch(request, env) {
    const origin = request.headers.get('Origin') || ALLOWED_ORIGIN;
    if (request.method === 'OPTIONS') return new Response(null, { status: 204, headers: cors(origin) });

    const url = new URL(request.url);
    try {
      if (request.method === 'GET' && url.pathname === '/api/health') return json({ ok: true, service: 'leadflow-assistant-api' }, 200, origin);
      if (request.method === 'POST' && url.pathname === '/api/chat') return await chat(request, env, origin);
      if (request.method === 'POST' && url.pathname === '/api/leads') return await createLead(request, env, origin);
      if (request.method === 'POST' && url.pathname === '/api/handoff') return await handoff(request, env, origin);
      return json({ error: 'Not found.' }, 404, origin);
    } catch (error) {
      console.error(error);
      return json({ error: 'Something went wrong. Please try again.' }, 500, origin);
    }
  },

  async scheduled(_controller, env) {
    if (env.DB) {
      await env.DB.prepare("DELETE FROM chat_logs WHERE created_at < datetime('now','-90 days')").run();
      await env.DB.prepare("DELETE FROM leads WHERE created_at < datetime('now','-90 days')").run();
    }
  },
};
