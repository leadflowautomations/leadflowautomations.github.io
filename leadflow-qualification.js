/* LeadFlow Assistant — qualification layer
 * Sends approved lead data to the secure backend.
 * No API keys or private credentials belong in this file.
 */
(() => {
  const state = { step: 0, data: {}, consent: false };
  const steps = [
    { key: 'businessType', q: 'What type of business do you run?', options: ['Professional services','Healthcare / clinic','Real estate','Gym / fitness','E-commerce','Other'] },
    { key: 'onlinePresence', q: 'Do you currently have a website or online customer channel?', options: ['Yes','No'] },
    { key: 'need', q: 'What would you most like to automate?', options: ['Customer questions','Lead capture','Lead follow-up','All of these'] },
    { key: 'package', q: 'Which level sounds closest to what you need?', options: ['Starter — $750','Professional — $1,500','Premium — $2,500','Not sure yet'] },
    { key: 'timeline', q: 'When would you ideally like to start?', options: ['Within 2–4 weeks','Later','Just exploring'] }
  ];

  window.LeadFlowQualification = {
    start(container) {
      if (!container) return;
      this.container = container;
      render();
    }
  };

  function render() {
    const c = LeadFlowQualification.container;
    if (state.step < steps.length) {
      const s = steps[state.step];
      c.innerHTML = `<div class="lfq"><div class="lfq-progress">Question ${state.step + 1} of ${steps.length}</div><h3>${escapeHtml(s.q)}</h3><div class="lfq-options">${s.options.map(o => `<button type="button" data-option="${escapeAttr(o)}">${escapeHtml(o)}</button>`).join('')}</div></div>`;
      c.querySelectorAll('[data-option]').forEach(b => b.addEventListener('click', () => { state.data[s.key] = b.dataset.option; state.step++; render(); }));
      return;
    }
    c.innerHTML = `<div class="lfq"><h3>You're almost there.</h3><p>Would you like David to follow up about your automation needs?</p><label><input id="lfqConsent" type="checkbox"> I agree that Lead Flow Automation may use my contact information to follow up.</label><div class="lfq-fields"><input id="lfqName" placeholder="Your name" autocomplete="name"><input id="lfqEmail" type="email" placeholder="Email address" autocomplete="email"></div><button type="button" id="lfqSubmit">Request consultation</button><p class="lfq-note">Your contact information is submitted only after consent.</p><p id="lfqStatus" class="lfq-status" role="status" aria-live="polite"></p></div>`;
    c.querySelector('#lfqSubmit').addEventListener('click', submitFromForm);
  }

  async function submitFromForm() {
    const c = LeadFlowQualification.container;
    const submit = c.querySelector('#lfqSubmit');
    const status = c.querySelector('#lfqStatus');
    const consent = c.querySelector('#lfqConsent').checked;
    const name = c.querySelector('#lfqName').value.trim();
    const email = c.querySelector('#lfqEmail').value.trim();
    if (!consent) return setStatus(status, 'Please give consent before submitting your contact details.');
    if (!name || !email) return setStatus(status, 'Please enter your name and email.');
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) return setStatus(status, 'Please enter a valid email address.');

    state.consent = true;
    state.data.name = name;
    state.data.email = email;
    submit.disabled = true;
    setStatus(status, 'Submitting your consultation request…');

    try {
      const response = await fetch('/api/leads', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ...state.data, consent: true })
      });
      const result = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(result.error || 'Unable to submit your request.');
      c.innerHTML = `<div class="lfq"><h3>Request received. ✅</h3><p>Thanks, ${escapeHtml(name)}. David will follow up about your automation needs.</p><p class="lfq-note">You can also email leadflowautomation.dav@gmail.com if you need anything immediately.</p></div>`;
    } catch (error) {
      submit.disabled = false;
      setStatus(status, error.message || 'Something went wrong. Please try again.');
    }
  }

  function setStatus(el, message) {
    if (el) el.textContent = message;
  }

  const escapeHtml = s => String(s).replace(/[&<>"']/g, m => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[m]));
  const escapeAttr = escapeHtml;
})();
