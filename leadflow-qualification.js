/* LeadFlow Assistant — qualification layer
 * Collects approved lead data after consent and sends it to the secure backend.
 * No API keys or private credentials belong in this file.
 */
(() => {
  const state = { step: 0, data: {}, consent: false };
  const steps = [
    { key: 'businessType', q: 'What type of business do you run?', options: ['Professional services','Healthcare / clinic','Real estate','Gym / fitness','E-commerce','Other'] },
    { key: 'onlinePresence', q: 'Do you currently have a website or online customer channel?', options: ['Yes','No'] },
    { key: 'need', q: 'What would you most like to automate?', options: ['Customer questions','Lead capture','Lead follow-up','All of these'] },
    { key: 'packageInterest', q: 'Which level sounds closest to what you need?', options: ['Starter — $750','Professional — $1,500','Premium — $2,500','Not sure yet'] },
    { key: 'timeline', q: 'When would you ideally like to start?', options: ['Within 2–4 weeks','Later','Just exploring'] }
  ];

  const API_BASE = (window.LEADFLOW_API_BASE || '').replace(/\/$/, '');

  window.LeadFlowQualification = {
    start(container) {
      if (!container) return;
      this.container = container;
      state.step = 0;
      state.data = {};
      state.consent = false;
      render();
    }
  };

  function render() {
    const c = LeadFlowQualification.container;
    if (!c) return;

    if (state.step < steps.length) {
      const s = steps[state.step];
      c.innerHTML = `<div class="lfq"><div class="lfq-progress">Question ${state.step + 1} of ${steps.length}</div><h3>${escapeHtml(s.q)}</h3><div class="lfq-options">${s.options.map(o => `<button type="button" data-option="${escapeAttr(o)}">${escapeHtml(o)}</button>`).join('')}</div></div>`;
      c.querySelectorAll('[data-option]').forEach(b => b.addEventListener('click', () => {
        state.data[s.key] = b.dataset.option;
        state.step++;
        render();
      }));
      return;
    }

    c.innerHTML = `<div class="lfq"><h3>You're almost there.</h3><p>I'll use these answers to prepare your consultation request. Would you like David to follow up?</p><div class="lfq-fields"><input id="lfqBusinessName" placeholder="Business name" autocomplete="organization"><input id="lfqName" placeholder="Your name" autocomplete="name"><input id="lfqEmail" type="email" placeholder="Email address" autocomplete="email"><input id="lfqPhone" type="tel" placeholder="Phone (optional)" autocomplete="tel"></div><label class="lfq-consent"><input id="lfqConsent" type="checkbox"> I agree that Lead Flow Automation may use my contact information to follow up about my request.</label><button type="button" id="lfqSubmit">Request consultation</button><p class="lfq-note">Your contact information is submitted only after consent.</p><p id="lfqStatus" class="lfq-status" role="status" aria-live="polite"></p></div>`;
    c.querySelector('#lfqSubmit').addEventListener('click', submitFromForm);
  }

  async function submitFromForm() {
    const c = LeadFlowQualification.container;
    const submit = c.querySelector('#lfqSubmit');
    const status = c.querySelector('#lfqStatus');
    const consent = c.querySelector('#lfqConsent').checked;
    const businessName = c.querySelector('#lfqBusinessName').value.trim();
    const name = c.querySelector('#lfqName').value.trim();
    const email = c.querySelector('#lfqEmail').value.trim();
    const phone = c.querySelector('#lfqPhone').value.trim();

    if (!consent) return setStatus(status, 'Please give consent before submitting your contact details.');
    if (!businessName || !name || !email) return setStatus(status, 'Please enter your business name, name and email.');
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) return setStatus(status, 'Please enter a valid email address.');

    state.consent = true;
    state.data.businessName = businessName;
    state.data.name = name;
    state.data.email = email;
    state.data.phone = phone;
    state.data.consent = true;
    state.data.consentTimestamp = new Date().toISOString();
    state.data.conversationId = getConversationId();

    submit.disabled = true;
    setStatus(status, 'Submitting your consultation request…');

    try {
      const response = await fetch(`${API_BASE}/api/leads`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(state.data)
      });
      const result = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(result.error || 'Unable to submit your request.');

      c.innerHTML = `<div class="lfq"><h3>Request received. ✅</h3><p>Thanks, ${escapeHtml(name)}. David will follow up about your automation needs.</p><p class="lfq-note">Your consultation request has been securely submitted.</p></div>`;
    } catch (error) {
      submit.disabled = false;
      setStatus(status, error.message || 'Something went wrong. Please try again.');
    }
  }

  function getConversationId() {
    try {
      const key = 'leadflow_conversation_id';
      let id = sessionStorage.getItem(key);
      if (!id) {
        id = crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random().toString(36).slice(2)}`;
        sessionStorage.setItem(key, id);
      }
      return id;
    } catch {
      return `${Date.now()}-${Math.random().toString(36).slice(2)}`;
    }
  }

  function setStatus(el, message) {
    if (el) el.textContent = message;
  }

  const escapeHtml = s => String(s).replace(/[&<>"']/g, m => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[m]));
  const escapeAttr = escapeHtml;
})();
