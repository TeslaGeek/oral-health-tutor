(function () {
  // --- read boot JSON (never HTML-escaped) ---
  const bootEl = document.getElementById('patient-builder-boot');
  let BOOT = {};
  try { BOOT = JSON.parse(bootEl?.textContent || '{}'); } catch (_) {}

  const CSRF = (document.querySelector('meta[name="csrf-token"]')||{}).content || (BOOT.csrf || '');
  const pid  = BOOT.pid;
  const P    = typeof BOOT.p  === 'string' ? JSON.parse(BOOT.p)  : (BOOT.p  || {});
  const UI   = typeof BOOT.ui === 'string' ? JSON.parse(BOOT.ui) : (BOOT.ui || {});
  const MODE = UI.mode || 'staff_view';

  // --- helpers ---
  function showToast(msg, ok=true) {
    let c = document.getElementById('toastContainer');
    if (!c) { c = document.createElement('div'); c.id='toastContainer'; c.style.cssText='position:fixed;bottom:1rem;right:1rem;z-index:1055'; document.body.appendChild(c); }
    const el = document.createElement('div');
    el.className = ok ? 'toast toast-success' : 'toast toast-error';
    el.textContent = msg;
    c.appendChild(el);
    setTimeout(()=>el.remove(), 4000);
  }
  function showSpinner(v){ document.getElementById('fullPageSpinner')?.classList.toggle('d-none', !v); }

  // --- uploads (presigned) ---
  async function presignAndUpload(field, file) {
    try {
      const r = await fetch(`/staff/patients/${pid}/media/presign`, {
        method:'POST',
        headers:{'Content-Type':'application/json','X-CSRFToken':CSRF},
        body: JSON.stringify({ field, filename:file.name, content_type:file.type, size:file.size })
      });
      if(!r.ok) throw new Error('Presign failed');
      const data = await r.json();
      if((data.method||'PUT').toUpperCase()==='POST') {
        const fd = new FormData();
        Object.entries(data.fields||{}).forEach(([k,v])=>fd.append(k,v));
        fd.append('file', file);
        const up = await fetch(data.upload_url, { method:'POST', body:fd });
        if(!up.ok) throw new Error('Upload failed');
      } else {
        const up = await fetch(data.upload_url, { method:'PUT', headers:{'Content-Type':file.type||'application/octet-stream'}, body:file });
        if(!up.ok) throw new Error('Upload failed');
      }
      await patchPatient({ [field]: data.public_url });
      document.getElementById(field).value = data.public_url;
      showToast('Uploaded successfully');
    } catch(e){ showToast(e.message||'Upload failed', false); }
  }

  async function patchPatient(payload){
    showSpinner(true);
    try{
      const r = await fetch(`/staff/patients/${pid}`, {
        method:'PATCH',
        headers:{'Content-Type':'application/json','X-CSRFToken':CSRF},
        body: JSON.stringify(payload)
      });
      showToast(r.ok ? 'Saved' : 'Save failed', r.ok);
    } catch(e) {
      showToast('Save failed', false);
    } finally { showSpinner(false); }
  }

  // --- enhance media inputs ---
  const MEDIA_FIELDS = [
    'oph_L_img_url',
    'oph_R_img_url',
    'oct_L_img_url',
    'oct_R_img_url',
    'visual_field_L_img_url',
    'visual_field_R_img_url',
    'anterior_seg_L_img_url',
    'anterior_seg_R_img_url',
    'other_media_L_img_url',
    'other_media_R_img_url'
  ];
  MEDIA_FIELDS.forEach(fld => {
    const input = document.getElementById(fld);
    if(!input) return;
    const btn = document.createElement('button');
    btn.textContent = 'Upload…';
    btn.type = 'button';
    btn.className = 'btn btn-primary btn-sm';
    btn.style.marginTop = '4px';
    btn.addEventListener('click', async () => {
      const file = await new Promise(res => { const inp = document.createElement('input'); inp.type='file'; inp.accept='image/*'; inp.onchange=()=>res(inp.files[0]); inp.click(); });
      if(file) presignAndUpload(fld, file);
    });
    input.parentNode.appendChild(btn);
  });

  // --- checks / submit / approve wiring ---
  async function runChecks(){
    showSpinner(true);
    try{
      const r = await fetch(`/staff/patients/${pid}/validate`, {method:'POST', headers:{'X-CSRFToken':CSRF}});
      const {errors=[], warnings=[]} = await r.json();
      const box = document.getElementById('issues');
      if (box){
        box.innerHTML = '';
        if(errors.length) box.insertAdjacentHTML('beforeend', `<div><strong>Errors</strong><ul>${errors.map(e=>`<li>${e}</li>`).join('')}</ul></div>`);
        if(warnings.length) box.insertAdjacentHTML('beforeend', `<div><strong>Warnings</strong><ul>${warnings.map(e=>`<li>${e}</li>`).join('')}</ul></div>`);
        if(!errors.length && !warnings.length) box.textContent = 'All good ✅';
      }
      showToast(errors.length? 'Checks found issues' : 'Checks passed');
    } finally { showSpinner(false); }
  }

  document.getElementById('btn-submit')?.addEventListener('click', async () => {
    showSpinner(true);
    try { const r = await fetch(`/staff/patients/${pid}/submit`, {method:'POST', headers:{'X-CSRFToken':CSRF}}); showToast(r.ok? 'Submitted for review' : 'Submit failed', r.ok); }
    finally { showSpinner(false); }
  });

  document.getElementById('btn-approve')?.addEventListener('click', async () => {
    showSpinner(true);
    try { const r = await fetch(`/staff/patients/${pid}/approve`, {method:'POST', headers:{'X-CSRFToken':CSRF}}); showToast(r.ok? 'Approved' : 'Approve failed', r.ok); }
    finally { showSpinner(false); }
  });
})();
