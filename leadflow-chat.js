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
    [/who is david|who.*david|what does david do|what.*david.*do|founder.*david/i, 'David Elijah is the founder and lead automation specialist behind Lead Flow Automation. He works with small businesses to design and implement AI-powered chatbots, lead-capture systems, customer-support automation and follow-up workflows. If you would like to speak with David about your business, you can schedule a 15-minute consultation using the button at the top of the page.'],
    [/can i speak to david|talk to david|speak with david|contact david/i, 'Absolutely. David Elijah is the founder and lead automation specialist at Lead Flow Automation. If you would like to discuss your business with him directly, you can schedule a 15-minute consultation using the button at the top of the page.'],
    [/price|cost|expensive|pricing|how much|budget/i, 'Absolutely. Lead Flow Automation currently has three packages: Starter at $750, Professional at $1,500, and Premium at $2,500. If you tell me what you want to automate, I can help you figure out which level makes sense rather than pushing you toward the most expensive option.'],
    [/how long|timeline|days|delivery|deliver|when.*ready/i, 'Typical delivery is 5 business days for Starter, 7 for Professional, and 10 for Premium. The exact timeline depends on the scope and integrations you need.'],
    [/capture|lead|prospect|qualif|customer.*information/i, 'Yes. We can design the assistant to qualify visitors, collect relevant information with consent, and hand qualified opportunities to you instead of leaving you to chase every conversation manually.'],
    [/platform|whatsapp|messenger|instagram|channel|where.*work/i, 'The website is the primary channel. WhatsApp, Messenger and Instagram can be added depending on the project and the platform’s integration requirements. If you tell me where your customers currently talk to you, I can help point you toward the right setup.'],
    [/code|coding|technical|developer|programming/i, 'You do not need to code it yourself. Lead Flow Automation handles the implementation and can tailor the system around your existing website and workflow.'],
    [/maintenance|support|after launch|monthly|update|updates/i, 'Yes. Optional maintenance is $200/month and can cover ongoing support, improvements and adjustments after launch. The exact support scope can be agreed with David.'],
    [/human|custom quote|person|someone|talk.*you/i, 'Absolutely. If your request needs a human or a custom decision, I can hand it over to David. You can also schedule a 15-minute consultation through the button at the top of the page.'],
    [/chatbot|what is ai|what do you do|what.*build|what.*offer/i, 'We build custom AI chatbots and lead-flow automation for small businesses. The assistant can answer customer questions, qualify prospects, capture leads with consent and guide people toward the right next step — even outside business hours.'],
    [/crm|google sheets|email|integration|integrate|connect/i, 'Yes. Professional and Premium can include integrations such as email, Google Sheets or supported CRM systems. The best option depends on where you currently manage your leads.'],
    [/24|offline|always|after hours|weekend|night/i, 'A properly deployed assistant can operate 24/7, so customers can get answers and start the lead process even when you are unavailable.'],
    [/website|embed|install|add to my site|wordpress|html/i, 'Yes. We can embed the assistant into most modern websites. The conversation can then be tailored around your services, FAQs and lead process.'],
    [/faq|knowledge|train|training|documents|learn.*business/i, 'Yes. Your FAQs, website content, documents and business information can be used to shape the assistant’s knowledge and behavior.'],
    [/refund|guarantee|contract|terms/i, 'For project-specific terms such as guarantees, refunds or contracts, I do not want to guess. I can have David confirm the exact terms for you.'],
    [/restaurant|salon|real estate|agency|clinic|shop|business/i, 'Yes — the system can be tailored to different small-business workflows. The useful next question is what your customers usually ask and what you currently do when someone becomes interested.'],
    [/help|start|begin|interested|need.*chatbot|want.*chatbot/i, 'Great. The easiest place to start is with your goal: tell me what kind of business you run, what you want the assistant to handle, and where your customers currently contact you. I can help you think through the right setup.']
  ];

  function replyFallback(text) {
    for (const [pattern, answer] of fallback) if (pattern.test(text)) return answer;
    waitingForEmail = true;
    return 'That sounds like something worth looking at specifically. I can have David get back to you about it. What’s the best email address to reach you?';
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
    history = history.slice(-16);
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
      history = history.slice(-16);
    } catch (error) {
      thinking.remove();
      const answer = replyFallback(text);
      add(body, answer, 'bot');
      history.push({ role: 'user', content: text }, { role: 'assistant', content: answer });
      history = history.slice(-16);
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
