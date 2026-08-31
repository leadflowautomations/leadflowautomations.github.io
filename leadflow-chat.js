/* LeadFlow Assistant — live AI chat layer
 * Uses the production Cloudflare Worker AI endpoint and keeps a local
 * fallback so the demo remains usable if the AI service is temporarily down.
 */
(() => {
  const API_BASE = (window.LEADFLOW_API_BASE || 'https://leadflow-assistant-api.leadflowautomations-dav.workers.dev').replace(/\/$/, '');
  let history = [];
  let busy = false;

  const fallback = [
    [/price|cost|expensive/i, 'Packages start at $750. Starter is $750, Professional is $1,500, and Premium is $2,500. Optional maintenance is $200/month.'],
    [/how long|timeline|days|delivery/i, 'Starter takes 5 business days, Professional 7 days, and Premium 10 days.'],
    [/capture|lead/i, 'Yes. LeadFlow can capture and qualify prospects after they give consent, then route qualified requests to a human.'],
    [/platform|whatsapp|messenger|instagram/i, 'Website is the primary channel. Messenger, WhatsApp and Instagram can be added depending on the project requirements.'],
    [/code|coding/i, 'No coding knowledge is required from you. Lead Flow Automation handles implementation.'],
    [/human|speak|david|custom quote/i, 'Absolutely. I can connect you with David for custom requirements. Email leadflowautomation.dav@gmail.com.'],
    [/chatbot|what is ai/i, 'An AI chatbot answers customer questions, guides conversations and can capture leads while your business is offline.'],
    [/crm|google sheets|email/i, 'Professional and Premium can include email, Google Sheets or supported CRM integrations.'],
    [/24|offline|always/i, 'A properly deployed chatbot can operate continuously and answer customers 24/7.']
  ];

  function replyFallback(text) {
    for (const [pattern, answer] of fallback) if (pattern.test(text)) return answer;
    return 'I can help with pricing, timelines, services, lead capture and integrations. If you need a custom quote or human assistance, I can connect you with David at leadflowautomation.dav@gmail.com.';
  }

  function add(body, text, cls) {
    const d = document.createElement('div');
    d.className = `bubble ${cls}`;
    d.textContent = text;
    body.appendChild(d);
    body.scrollTop = body.scrollHeight;
    return d;
  }

  async function send(body, input, text) {
    text = String(text || '').trim();
    if (!text || busy) return;
    add(body, text, 'user');
    input.value = '';
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
      add(body, replyFallback(text), 'bot');
      history.push({ role: 'user', content: text }, { role: 'assistant', content: replyFallback(text) });
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

    // The original demo has local handlers. Capture-phase interception prevents
    // those handlers from firing twice while preserving the existing markup.
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
