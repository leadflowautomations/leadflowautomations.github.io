/* LeadFlow Assistant — qualification layer (frontend only)
 * No personal data is stored or transmitted by this file.
 * Connect its submitLead() hook to a secure backend when one is available.
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
    c.innerHTML = `<div class="lfq"><h3>You're almost there.</h3><p>Would you like David to follow up about your automation needs?</p><label><input id="lfqConsent" type="checkbox"> I agree that Lead Flow Automation may use my contact information to follow up.</label><div class="lfq-fields"><input id="lfqName" placeholder="Your name"><input id="lfqEmail" type="email" placeholder="Email address"></div><button type="button" id="lfqSubmit">Request consultation</button><p class="lfq-note">Your details should only be sent to a secure backend after consent. This frontend demo does not store them.</p></div>`;
    c.querySelector('#lfqSubmit').addEventListener('click', () => {
      const consent = c.querySelector('#lfqConsent').checked;
      const name = c.querySelector('#lfqName').value.trim();
      const email = c.querySelector('#lfqEmail').value.trim();
      if (!consent) return alert('Please give consent before submitting your contact details.');
      if (!name || !email) return alert('Please enter your name and email.');
      state.consent = true; state.data.name = name; state.data.email = email; submitLead({ ...state.data, consent: true, consentTimestamp: new Date().toISOString() });
    });
  }

  function submitLead(lead) {
    // Backend integration point. Do not add API keys or private credentials here.
    const subject = encodeURIComponent('Lead Flow Automation — Consultation Request');
    const body = encodeURIComponent(`Name: ${lead.name}\nEmail: ${lead.email}\nBusiness: ${lead.businessType}\nOnline presence: ${lead.onlinePresence}\nAutomation need: ${lead.need}\nPackage interest: ${lead.package}\nStart timeframe: ${lead.timeline}\nConsent: yes`);
    window.location.href = `mailto:leadflowautomation.dav@gmail.com?subject=${subject}&body=${body}`;
  }
  const escapeHtml = s => String(s).replace(/[&<>"']/g, m => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[m]));
  const escapeAttr = escapeHtml;
})();
