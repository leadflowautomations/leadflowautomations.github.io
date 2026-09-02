/* LeadFlow Assistant — live AI chat layer
 * Uses the production Cloudflare Worker AI endpoint and keeps a local
 * fallback so the demo remains usable if the AI service is temporarily down.
 */
(() => {
  const API_BASE = (window.LEADFLOW_API_BASE || 'https://leadflow-assistant-api.leadflowautomations-dav.workers.dev').replace(/\/$/, '');
  let history = [];
  let busy = false;
  let waitingForEmail = false;

  const fallback = [
    [/price|cost|expensive|pricing/i, 'Packages start at $750. Starter is $750, Professional is $1,500, and Premium is $2,500. Optional maintenance is $200/month.'],
    [/how long|timeline|days|delivery|deliver/i, 'Starter takes 5 business days, Professional 7 days, and Premium 10 days.'],
    [/capture|lead|prospect|qualif/i, 'Yes. LeadFlow can capture and qualify prospects after they give consent, then route qualified requests to a human.'],
    [/platform|whatsapp|messenger|instagram|channel/i, 'Website is the primary channel. Messenger, WhatsApp and Instagram can be added depending on the project requirements.'],
    [/code|coding|technical/i, 'No coding knowledge is required from you. Lead Flow Automation handles implementation.'],
    [/maintenance|support|after launch|monthly/i, 'Optional maintenance is $200/month and can cover ongoing support and improvements after launch.'],
    [/human|speak|david|custom quote|person|someone/i, 'Absolutely. I can connect you with David for custom requirements. Email leadflowautomation.dav@gmail.com or use the consultation flow above.'],
    [/chatbot|what is ai|what do you do/i, 'An AI chatbot answers customer questions, guides conversations and can capture leads while your business is offline.'],
    [/crm|google sheets|email|integration|integrate/i, 'Professional and Premium can include email, Google Sheets or supported CRM integrations.'],
    [/24|offline|always|after hours|weekend/i, 'A properly deployed chatbot can operate continuously and answer customers 24/7.'],
    [/website|embed|install|add to my site/i, 'Yes. We can embed the assistant into most modern websites and tailor its conversation flow to your business.'],
    [/faq|knowledge|train|training|documents/i, 'Yes. FAQs, documents and website content can be used to shape the assistant’s knowledge and responses.'],
    [/refund|guarantee/i, 'For project-specific terms such as guarantees or refunds, I can have David confirm the details for you.']
  ];

  function replyFallback(text) {
    for (const [pattern, answer] of fallback) if (pattern.test(text)) return answer;
    waitingForEmail = true;
    return 'I can have David get back to you about that. What’s your email?';
  }

  function add(body, text, cls) {
    const d = document.createElement('div');
    d.className = `bubble ${cls}`;
    d.textContent = text;
    body.appendChild(d);
    body.scrollTop = body.scrollHeight;
    return d;
  }

  function isEmail(text) {
    return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(String(text || '').trim());
  }

  function handleEmail(body, input, text) {
    const email = String(text || '').trim();
    if (!isEmail(email)) {
      add(body, 'Please enter a valid email address so David knows where to reach you.', 'bot');
      return true;
    }
    waitingForEmail = false;
    try { sessionStorage.setItem('leadflow_callback_email', email); } catch (_) {}
    add(body, `Thanks — I’ve noted ${email} for this conversation. David can follow up about your request.`, 'bot');
    history.push({ role: 'user', content: email }, { role: 'assistant', content: `Thanks — I’ve noted ${email} for this conversation. David can follow up about your request.` });
    history = history.slice(-12);
    return true;
  }

  async function send(body, input, text) {
    text = String(text || '').trim();
    if (!text || busy) return;
    add(body, text, 'user');
    input.value = '';

    if (waitingForEmail && isEmail(text)) {
      handleEmail(body, input, text);
      input.focus();
      return;
    }

    busy = true;
    const thinking = add(body, 'Thinking…', 'bot');

    try {
      const response = await fetch(`${API_BASE}/api/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
        body: JSON.stringify({ message: text, history })
      });
      const result = await response.json().catch(() => ({}));
      if (!response.ok || !result.answer) throw new Error(result.error || `AI service returned ${response.status}`);
      thinking.remove();
      add(body, result.answer, 'bot');
      history.push({ role: 'user', content: text }, { role: 'assistant', content: result.answer });
      history = history.slice(-12);
    } catch (error) {
      thinking.remove();
      const answer = replyFallback(text);
      add(body, answer, 'bot');
      history.push({ role: 'user', content: text }, { role: 'assistant', content: answer });
      history = history.slice(-12);
      console.warn('LeadFlow AI chat unavailable; fallback response used.', error);
    } finally {
      busy = false;
      input.focus();
    }
  }

  function init() {
    const body = document.getElementById('chatBody');
    const input = document.getElementById('chatInput');
    const button = document.getElementById('sendBtn');
    if (!body || !input || !button || button.dataset.aiBound) return;

    button.dataset.aiBound = 'true';
    button.addEventListener('click', event => {
      event.preventDefault();
      event.stopImmediatePropagation();
      send(body, input, input.value);
    }, true);

    input.addEventListener('keydown', event => {
      if (event.key === 'Enter') {
        event.preventDefault();
        event.stopImmediatePropagation();
        send(body, input, input.value);
      }
    }, true);

    document.querySelectorAll('.chip[data-q]').forEach(chip => {
      chip.addEventListener('click', event => {
        event.preventDefault();
        event.stopImmediatePropagation();
        send(body, input, chip.dataset.q);
      }, true);
    });
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init); else init();
})();
