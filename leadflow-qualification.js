/* LeadFlow Assistant — qualification layer */
(() => {
  const state = { step: 0, data: {}, consent: false };
  const steps = [
    { key: 'businessType', q: 'What type of business do you run?', options: ['Professional services','Healthcare / clinic','Real estate','Gym / fitness','E-commerce','Other'] },
    { key: 'onlinePresence', q: 'Do you currently have a website or online customer channel?', options: ['Yes','No'] },
    { key: 'need', q: 'What would you most like to automate?', options: ['Customer questions','Lead capture','Lead follow-up','All of these'] },
    { key: 'packageInterest', q: 'Which level sounds closest to what you need?', options: ['Starter — $750','Professional — $1,500','Premium — $2,500','Not sure yet'] },
    { key: 'timeline', q: 'When would you ideally like to start?', options: ['Within 2–4 weeks','Later','Just exploring'] }
  ];
  const API_BASE = (window.LEADFLOW_API_BASE || 'https://leadflow-assistant-api.leadflowautomations-dav.workers.dev').replace(/\/$/, '');
  const FALLBACK_EMAIL = 'leadflowautomation.dav@gmail.com';

  window.LeadFlowQualification = {
    start(container) { if (!container) return; this.container = container; state.step = 0; state.data = {}; state.consent = false; render(); },
    open() { openQualification(); }
  };

  function render() {
    const c = LeadFlowQualification.container; if (!c) return;
    if (state.step < steps.length) {
      const s = steps[state.step];
      c.innerHTML = `<div class="lfq"><div class="lfq-progress">Question ${state.step + 1} of ${steps.length}</div><h3>${escapeHtml(s.q)}</h3><div class="lfq-options">${s.options.map(o => `<button type="button" data-option="${escapeAttr(o)}">${escapeHtml(o)}</button>`).join('')}</div></div>`;
      c.querySelectorAll('[data-option]').forEach(b => b.addEventListener('click', () => { state.data[s.key] = b.dataset.option; state.step++; render(); }));
      return;
    }
    c.innerHTML = `<div class="lfq"><h3>You're almost there.</h3><p>I'll use these answers to prepare your consultation request. Would you like David to follow up?</p><div class="lfq-fields"><input id="lfqBusinessName" placeholder="Business name" autocomplete="organization"><input id="lfqName" placeholder="Your name" autocomplete="name"><input id="lfqEmail" type="email" placeholder="Email address" autocomplete="email"><input id="lfqPhone" type="tel" placeholder="Phone (optional)" autocomplete="tel"></div><label class="lfq-consent"><input id="lfqConsent" type="checkbox"> I agree that Lead Flow Automation may use my contact information to follow up about my request.</label><button type="button" id="lfqSubmit">Request consultation</button><p class="lfq-note">Your contact information is submitted only after consent.</p><p id="lfqStatus" class="lfq-status" role="status" aria-live="polite"></p></div>`;
    c.querySelector('#lfqSubmit').addEventListener('click', submitFromForm);
  }

  async function submitFromForm() {
    const c = LeadFlowQualification.container, submit = c.querySelector('#lfqSubmit'), status = c.querySelector('#lfqStatus');
    const consent = c.querySelector('#lfqConsent').checked;
    const businessName = c.querySelector('#lfqBusinessName').value.trim();
    const name = c.querySelector('#lfqName').value.trim();
    const email = c.querySelector('#lfqEmail').value.trim();
    const phone = c.querySelector('#lfqPhone').value.trim();
    if (!consent) return setStatus(status, 'Please give consent before submitting your contact details.');
    if (!businessName || !name || !email) return setStatus(status, 'Please enter your business name, name and email.');
    if (!/^([^\s@]+)@([^\s@]+)\.([^\s@]+)$/.test(email)) return setStatus(status, 'Please enter a valid email address.');

    state.consent = true;
    state.data = { ...state.data, businessName, name, email, phone, consent: true, consentTimestamp: new Date().toISOString(), conversationId: getConversationId() };
    submit.disabled = true; setStatus(status, 'Submitting your consultation request…');

    try {
      const response = await fetch(`${API_BASE}/api/leads`, { method: 'POST', headers: { 'Content-Type': 'application/json', Accept: 'application/json' }, body: JSON.stringify(state.data) });
      const result = await response.json().catch(() => ({}));
      if (response.ok) { showSuccess(c, name); return; }
      console.warn('LeadFlow Worker delivery failed:', result.error || response.status);
      showDeliveryError(c, result.error || `The delivery service returned HTTP ${response.status}. Your details were stored, but the email could not be confirmed.`);
    } catch (error) {
      console.error('LeadFlow Worker request failed:', error);
      showDeliveryError(c, 'The delivery service could not be reached. Your details may still be stored; please use the email backup below.');
    } finally { submit.disabled = false; }
  }

  function showSuccess(c, name) {
    c.innerHTML = `<div class="lfq lfq-success"><h3>Consultation request received. ✅</h3><p>Thanks, ${escapeHtml(name)}. Your request was accepted by the LeadFlow delivery service. David will follow up.</p><p class="lfq-note">You can close this window now.</p><button type="button" class="lfq-close-result" onclick="this.closest('.lfq-overlay')?.remove()">Done</button></div>`;
  }

  function showDeliveryError(c, message) {
    const safe = escapeHtml(message);
    const subject = encodeURIComponent(`Free consultation request — ${state.data.businessName}`);
    const body = encodeURIComponent(['Hello David,', '', 'I would like a free consultation for my business.', '', `Business: ${state.data.businessName}`, `Name: ${state.data.name}`, `Email: ${state.data.email}`, `Phone: ${state.data.phone || 'Not provided'}`, `Business type: ${state.data.businessType || 'Not provided'}`, `Online presence: ${state.data.onlinePresence || 'Not provided'}`, `Automation need: ${state.data.need || 'Not provided'}`, `Package interest: ${state.data.packageInterest || 'Not provided'}`, `Timeline: ${state.data.timeline || 'Not provided'}`, '', 'Consent: Yes', `Consent timestamp: ${state.data.consentTimestamp}`].join('\n'));
    c.innerHTML = `<div class="lfq"><h3>Delivery needs attention.</h3><p>${safe}</p><p class="lfq-note">Your lead details remain available in this form. We will not falsely report that an email was delivered.</p><a class="lfq-email-fallback" href="mailto:${FALLBACK_EMAIL}?subject=${subject}&body=${body}">Open email backup →</a><p class="lfq-note">Nothing is sent until you press Send.</p></div>`;
  }

  function getConversationId() {
    try { const key = 'leadflow_conversation_id'; let id = sessionStorage.getItem(key); if (!id) { id = (window.crypto && typeof window.crypto.randomUUID === 'function') ? window.crypto.randomUUID() : `${Date.now()}-${Math.random().toString(36).slice(2)}`; sessionStorage.setItem(key, id); } return id; }
    catch { return `${Date.now()}-${Math.random().toString(36).slice(2)}`; }
  }
  function setStatus(el, message) { if (el) el.textContent = message; }
  function injectStyles() {
    if (document.getElementById('lfq-styles')) return;
    const style = document.createElement('style'); style.id = 'lfq-styles';
    style.textContent = `.lfq-launch{border:1px solid #5b8cff88!important;background:linear-gradient(135deg,#5b8cff22,#7c5cff22)!important;color:#dce6ff!important}.lfq-overlay{position:fixed;inset:0;z-index:9999;display:grid;place-items:center;padding:18px;background:#02050bcc;backdrop-filter:blur(8px)}.lfq-modal{width:min(560px,100%);max-height:90vh;overflow:auto;background:linear-gradient(145deg,#111b2b,#0b121f);border:1px solid #33445f;border-radius:22px;box-shadow:0 30px 100px #000b;padding:22px;color:#f5f7fb}.lfq-modal-head{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:8px}.lfq-modal-head b{font-size:1rem}.lfq-close{border:1px solid #33445f;background:#ffffff08;color:#aebbd0;border-radius:10px;width:36px;height:36px;cursor:pointer;font-size:18px}.lfq-progress{color:#91adff;text-transform:uppercase;font-size:.68rem;font-weight:800;letter-spacing:.08em;margin-bottom:8px}.lfq h3{margin:0 0 8px;font-size:1.15rem}.lfq p{color:#9aa7ba;font-size:.84rem;margin:8px 0 16px}.lfq-options{display:grid;gap:9px}.lfq-options button,.lfq #lfqSubmit,.lfq-email-fallback,.lfq-close-result{border:1px solid #344563;background:#ffffff08;color:#eaf0ff;border-radius:12px;padding:12px;text-align:left;cursor:pointer;font-weight:700}.lfq-options button:hover{border-color:#5b8cff;background:#5b8cff18}.lfq-fields{display:grid;gap:9px}.lfq-fields input{width:100%;box-sizing:border-box;background:#0c1524;border:1px solid #2c3b53;border-radius:10px;padding:12px;color:#fff;outline:none}.lfq-fields input:focus{border-color:#5b8cff}.lfq-consent{display:flex;gap:9px;align-items:flex-start;margin:14px 0;color:#9aa7ba;font-size:.75rem;line-height:1.4}.lfq-consent input{margin-top:3px}.lfq #lfqSubmit{width:100%;text-align:center;background:linear-gradient(135deg,#5b8cff,#7c5cff);border:0;margin-top:4px}.lfq #lfqSubmit:disabled{opacity:.55;cursor:wait}.lfq-email-fallback,.lfq-close-result{display:block;width:100%;box-sizing:border-box;text-align:center;background:linear-gradient(135deg,#5b8cff,#7c5cff);border:0;text-decoration:none;margin-top:14px}.lfq-close-result{color:#fff}.lfq-note{font-size:.7rem!important;color:#708097!important;text-align:center}.lfq-status{color:#ffb4b4!important;min-height:20px;margin-bottom:0!important}.lfq-success h3{color:#c8ffd8}`;
    document.head.appendChild(style);
  }
  function openQualification() {
    if (document.querySelector('.lfq-overlay')) return; injectStyles();
    const overlay = document.createElement('div'); overlay.className = 'lfq-overlay';
    overlay.innerHTML = `<div class="lfq-modal" role="dialog" aria-modal="true" aria-label="Lead qualification"><div class="lfq-modal-head"><b>LeadFlow Qualification</b><button class="lfq-close" type="button" aria-label="Close">×</button></div><div id="lfqMount"></div></div>`;
    document.body.appendChild(overlay); const close = () => overlay.remove(); overlay.querySelector('.lfq-close').addEventListener('click', close); overlay.addEventListener('click', e => { if (e.target === overlay) close(); }); LeadFlowQualification.start(overlay.querySelector('#lfqMount'));
  }
  function loadLiveChat() { if (document.getElementById('leadflow-live-chat')) return; const script = document.createElement('script'); script.id = 'leadflow-live-chat'; script.src = 'leadflow-chat.js?v=20260831-5'; script.async = true; document.head.appendChild(script); }
  function bindLaunchButton(button) { if (!button || button.dataset.lfqBound === 'true') return; button.dataset.lfqBound = 'true'; button.addEventListener('click', event => { event.preventDefault(); event.stopPropagation(); openQualification(); }, true); }
  function initLauncher() {
    injectStyles(); loadLiveChat(); const chips = document.querySelector('.chips');
    if (chips && !chips.querySelector('[data-lfq-launch]')) { const button = document.createElement('button'); button.type = 'button'; button.className = 'chip lfq-launch'; button.dataset.lfqLaunch = 'true'; button.textContent = 'Get a free consultation →'; chips.appendChild(button); }
    document.querySelectorAll('.actions .cta, [data-lfq-launch]').forEach(bindLaunchButton);
    if (!document.documentElement.dataset.lfqDelegated) { document.documentElement.dataset.lfqDelegated = 'true'; document.addEventListener('click', event => { const target = event.target instanceof Element ? event.target.closest('.actions .cta, [data-lfq-launch]') : null; if (!target) return; event.preventDefault(); event.stopPropagation(); openQualification(); }, true); }
    const heroCta = document.querySelector('.actions .cta'); if (heroCta) { heroCta.href = '#'; heroCta.textContent = 'Get a Free Consultation →'; heroCta.setAttribute('aria-label', 'Get a Free Consultation'); heroCta.dataset.lfqBound = 'true'; }
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', initLauncher); else initLauncher();
  const escapeHtml = s => String(s).replace(/[&<>\"']/g, m => ({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',"'":'&#039;'}[m]));
  const escapeAttr = escapeHtml;
})();
