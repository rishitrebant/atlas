(() => {
  'use strict';
  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
  const DEFAULT_KEY = 'change-me-in-.env';
  const state = { view: 'dashboard', students: [], credentials: [], logs: [], gateLogs: [], gateStatus: [], health: null, deviceKey: sessionStorage.getItem('atlasDeviceKey') || 'change-me-device-key', adminKey: sessionStorage.getItem('atlasAdminKey') || DEFAULT_KEY, verifying: false };
  const titles = { dashboard: 'Overview', students: 'Students', credentials: 'Credentials', gate: 'Campus gate', verify: 'Verify a credential', audit: 'Audit trail' };

  $('#adminKeyInput').value = state.adminKey;
  $('#deviceKeyInput').value = state.deviceKey;
  function escapeHtml(value) {
    return String(value ?? '').replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
  }
  function fmtDate(value) {
    if (!value) return '—';
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return String(value);
    return date.toLocaleString([], {year:'numeric', month:'short', day:'2-digit', hour:'2-digit', minute:'2-digit'});
  }
  function shortHash(hash, front = 12, back = 8) {
    if (!hash) return '—';
    const value = String(hash);
    return value.length > front + back + 3 ? `${value.slice(0, front)}…${value.slice(-back)}` : value;
  }
  function initials(name) { return String(name || '?').trim().split(/\s+/).slice(0,2).map(part => part[0] || '').join('').toUpperCase(); }
  function toast(message, type = '') {
    const node = document.createElement('div'); node.className = `toast ${type}`.trim(); node.textContent = message;
    $('#toastRegion').appendChild(node); window.setTimeout(() => node.remove(), 3900);
  }
  function setMessage(id, message, type = '') {
    const node = document.getElementById(id); if (!node) return;
    node.textContent = message; node.className = `form-message ${type}`.trim();
  }
  function setLoadingRow(id, colspan, message) {
    const target = document.getElementById(id); if (target) target.innerHTML = `<tr><td colspan="${colspan}" class="empty-cell">${escapeHtml(message)}</td></tr>`;
  }
  async function api(path, options = {}, admin = false) {
    const headers = new Headers(options.headers || {});
    if (options.body && !headers.has('Content-Type')) headers.set('Content-Type', 'application/json');
    if (admin) headers.set('X-Admin-Api-Key', state.adminKey);
    let response;
    try { response = await fetch(path, {...options, headers}); }
    catch (error) { throw new Error('Cannot reach the API. Confirm the backend is running at this address and reload the page.'); }
    const raw = await response.text();
    let data = null;
    if (raw) { try { data = JSON.parse(raw); } catch { data = raw; } }
    if (!response.ok) {
      let detail = data && typeof data === 'object' ? data.detail : null;
      if (Array.isArray(detail)) detail = detail.map(item => `${(item.loc || []).slice(-1)[0] || 'field'}: ${item.msg}`).join('; ');
      throw new Error(detail || `Request failed (${response.status} ${response.statusText})`);
    }
    return data;
  }
  function navigate(view) {
    if (!titles[view]) return;
    state.view = view;
    $$('.view').forEach(node => node.classList.toggle('active', node.id === `view-${view}`));
    $$('.nav-item').forEach(node => node.classList.toggle('active', node.dataset.view === view));
    $('#breadcrumbTitle').textContent = titles[view];
    if (view === 'students') loadStudents();
    if (view === 'credentials') { loadStudents(); loadCredentials(); }
    if (view === 'audit') loadLogs();
    if (view === 'gate') loadGate();
    window.scrollTo({top:0, behavior:'smooth'});
  }
  function resultPill(result) {
    const value = String(result || 'unknown').toLowerCase();
    const safe = ['verified','invalid','revoked'].includes(value) ? value : 'invalid';
    return `<span class="result-pill result-${safe}">${escapeHtml(value)}</span>`;
  }
  function statusPill(status) {
    const value = String(status || 'unknown').toLowerCase();
    const safe = ['active','revoked'].includes(value) ? value : 'revoked';
    return `<span class="status-pill status-${safe}">${escapeHtml(value)}</span>`;
  }
  function chainPill(chain) {
    if (!chain) return '';
    const s = String(chain.status || 'pending').toLowerCase();
    const safe = ['confirmed','pending','failed'].includes(s) ? s : 'pending';
    const tip = chain.tx_hash ? `tx ${chain.tx_hash}` : (chain.error || '');
    return `<span class="chain-pill chain-${safe}" title="${escapeHtml(tip)}">${safe === 'confirmed' ? '⛓ on-chain' : safe === 'failed' ? '⛓ chain failed' : '⛓ pending'}</span>`;
  }
  function gateResultPill(log) {
    return log.granted ? '<span class="result-pill result-verified">granted</span>' : `<span class="result-pill result-invalid">${escapeHtml(String(log.reason || 'denied').replace(/_/g, ' '))}</span>`;
  }
  async function loadGate() {
    setLoadingRow('gateTable', 6, 'Loading gate log…');
    try {
      [state.gateLogs, state.gateStatus] = await Promise.all([api('/gate/logs', {}, true), api('/gate/status', {}, true)]);
    } catch (error) {
      state.gateLogs = []; state.gateStatus = [];
      renderGate(); setLoadingRow('gateTable', 6, error.message);
      if (error.message.toLowerCase().includes('admin api key')) $('#keyPanel').hidden = false;
      return;
    }
    renderGate();
  }
  function renderGate() {
    const inside = state.gateStatus.filter(s => s.inside).length;
    $('#gateNavCount').textContent = inside;
    $('#statInside').textContent = `${inside} inside`;
    $('#gateBoard').innerHTML = state.gateStatus.length ? state.gateStatus.map(s => `<div class="gate-chip ${s.inside ? 'in' : 'out'}"><span class="avatar">${escapeHtml(initials(s.full_name))}</span><span><span class="person-name">${escapeHtml(s.full_name)}</span><span class="person-sub">${escapeHtml(s.student_id)} · ${escapeHtml(s.rfid_uid || 'no card')}</span></span><span class="gate-state">${s.inside ? 'INSIDE' : 'OUTSIDE'}</span></div>`).join('') : '<div class="empty-cell">No students yet.</div>';
    $('#gateTable').innerHTML = state.gateLogs.length ? state.gateLogs.map(l => `<tr><td>${escapeHtml(fmtDate(l.occurred_at))}</td><td><span class="person-name">${escapeHtml(l.student_id || 'unknown')}</span><span class="person-sub">${escapeHtml(l.rfid_uid_scanned)}</span></td><td>${escapeHtml(String(l.direction).replace('GateDirection.', ''))}</td><td>${gateResultPill(l)}</td><td>${chainPill(l.chain) || '<span class="hash-short">—</span>'}</td><td>${l.proof_hash ? `<button class="mini-btn" data-verify-hash="${escapeHtml(l.proof_hash)}" type="button">${escapeHtml(shortHash(l.proof_hash, 8, 6))}</button>` : '—'}</td></tr>`).join('') : '<tr><td colspan="6" class="empty-cell">No gate scans yet. Tap a card on the ESP32 or use the simulator.</td></tr>';
  }
  async function simulateScan(direction) {
    const uid = $('#simUid').value.trim();
    if (!uid) { setMessage('simScanMessage', 'Enter a card UID.', 'error'); return; }
    try {
      const res = await fetch('/gate/scan', { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Device-Api-Key': state.deviceKey }, body: JSON.stringify({ uid, direction }) });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail || `Request failed (${res.status})`);
      setMessage('simScanMessage', `${data.granted ? '✓' : '×'} ${data.student_name ? data.student_name + ': ' : ''}${data.message}`, data.granted ? 'success' : 'error');
      toast(data.message, data.granted ? 'success' : 'error');
      await loadGate();
      if (data.granted) setTimeout(loadGate, 2500); // pick up the confirmed chain status
    } catch (error) { setMessage('simScanMessage', error.message, 'error'); toast(error.message, 'error'); }
  }
  async function loadHealth() {
    const badge = $('#serverStatus');
    try {
      state.health = await api('/health');
      badge.className = 'server-status online'; badge.innerHTML = '<span class="status-dot"></span><span>API connected</span>';
      $('#statHealth').textContent = 'Operational'; $('#statPhase').textContent = `Phase ${state.health.phase || '1'} · chain ${state.health.blockchain || 'n/a'}${state.health.contract_configured === false ? ' · no contract set' : ''}`;
    } catch (error) {
      badge.className = 'server-status offline'; badge.innerHTML = '<span class="status-dot"></span><span>API offline</span>';
      $('#statHealth').textContent = 'Offline'; $('#statPhase').textContent = 'Start the FastAPI backend';
      $('#dashboardActivity').innerHTML = `<tr><td colspan="4" class="empty-cell">${escapeHtml(error.message)}</td></tr>`;
    }
  }
  function renderStudents() {
    const query = ($('#studentSearch').value || '').trim().toLowerCase();
    const visible = state.students.filter(student => [student.student_id, student.full_name, student.email, student.course].some(value => String(value || '').toLowerCase().includes(query)));
    $('#studentNavCount').textContent = state.students.length;
    $('#studentsTotalLabel').textContent = `${state.students.length} record${state.students.length === 1 ? '' : 's'}`;
    if (!visible.length) { setLoadingRow('studentsTable', 5, state.students.length ? 'No students match this search.' : 'No student records yet. Register the first student using the form.'); }
    else {
      $('#studentsTable').innerHTML = visible.map(student => `<tr>
        <td><div class="person-cell"><span class="avatar">${escapeHtml(initials(student.full_name))}</span><span><span class="person-name">${escapeHtml(student.full_name)}</span><span class="person-sub">${escapeHtml(student.student_id)} · ${escapeHtml(student.email)}</span></span></div></td>
        <td>${escapeHtml(student.course || '—')}</td><td><span class="hash-short">${escapeHtml(student.rfid_uid || '—')}</span></td><td>${escapeHtml(fmtDate(student.created_at))}</td>
        <td><button class="mini-btn" data-student-details="${escapeHtml(student.student_id)}" type="button">Details</button></td></tr>`).join('');
    }
    const select = $('#credentialStudentSelect');
    const prior = select.value;
    select.innerHTML = state.students.length ? '<option value="">Select a student</option>' + state.students.map(s => `<option value="${escapeHtml(s.student_id)}">${escapeHtml(s.full_name)} · ${escapeHtml(s.student_id)}</option>`).join('') : '<option value="">No students available — create one first</option>';
    if (state.students.some(s => s.student_id === prior)) select.value = prior;
    updateStats();
  }
  async function loadStudents() {
    setLoadingRow('studentsTable', 5, 'Loading students…');
    try { state.students = await api('/students', {}, true); renderStudents(); }
    catch (error) { state.students = []; renderStudents(); setLoadingRow('studentsTable', 5, error.message); if (error.message.toLowerCase().includes('admin api key')) $('#keyPanel').hidden = false; }
  }
  function renderCredentials() {
    $('#credentialNavCount').textContent = state.credentials.length;
    $('#credentialsTotalLabel').textContent = `${state.credentials.length} credential${state.credentials.length === 1 ? '' : 's'}`;
    if (!state.credentials.length) setLoadingRow('credentialsTable', 6, 'No credentials yet. Issue the first credential above.');
    else {
      $('#credentialsTable').innerHTML = state.credentials.map(credential => `<tr>
        <td><span class="person-name">${escapeHtml(credential.title)}</span><span class="person-sub">${escapeHtml(credential.credential_type)} · ${escapeHtml(credential.issued_by)}</span></td>
        <td>${escapeHtml(credential.student_id)}</td><td>${statusPill(credential.status)} ${chainPill(credential.chain)}</td>
        <td><button class="mini-btn" data-copy-hash="${escapeHtml(credential.proof_hash)}" type="button" title="Copy full proof hash">${escapeHtml(shortHash(credential.proof_hash))} ⧉</button></td>
        <td>${escapeHtml(fmtDate(credential.issued_at))}</td>
        <td><div class="row-actions"><button class="mini-btn" data-credential-details="${escapeHtml(credential.id)}" type="button">Details</button><button class="mini-btn" data-verify-hash="${escapeHtml(credential.proof_hash)}" type="button">Verify</button>${credential.status === 'active' ? `<button class="mini-btn danger" data-revoke="${escapeHtml(credential.id)}" data-title="${escapeHtml(credential.title)}" type="button">Revoke</button>` : ''}</div></td></tr>`).join('');
    }
    updateStats();
  }
  async function loadCredentials() {
    setLoadingRow('credentialsTable', 6, 'Loading credentials…');
    try { state.credentials = await api('/credentials', {}, true); renderCredentials(); }
    catch (error) { state.credentials = []; renderCredentials(); setLoadingRow('credentialsTable', 6, error.message); if (error.message.toLowerCase().includes('admin api key')) $('#keyPanel').hidden = false; }
  }
  function renderLogs() {
    const tbody = $('#auditTable');
    $('#statChecks').textContent = state.logs.length;
    if (!state.logs.length) setLoadingRow('auditTable', 4, 'No verification activity has been recorded yet.');
    else tbody.innerHTML = state.logs.map(log => `<tr><td>${resultPill(log.result)}</td><td><button class="mini-btn" data-verify-hash="${escapeHtml(log.proof_hash_checked)}" type="button">${escapeHtml(shortHash(log.proof_hash_checked))}</button></td><td>${escapeHtml(fmtDate(log.checked_at))}</td><td><span class="hash-short">${escapeHtml(shortHash(log.id, 8, 4))}</span></td></tr>`).join('');
    $('#dashboardActivity').innerHTML = state.logs.slice(0,5).length ? state.logs.slice(0,5).map(log => `<tr><td>${resultPill(log.result)}</td><td><span class="hash-short" title="${escapeHtml(log.proof_hash_checked)}">${escapeHtml(shortHash(log.proof_hash_checked))}</span></td><td>${escapeHtml(fmtDate(log.checked_at))}</td><td><span class="hash-short">${escapeHtml(shortHash(log.id, 8, 4))}</span></td></tr>`).join('') : '<tr><td colspan="4" class="empty-cell">No verification checks yet.</td></tr>';
    updateStats();
  }
  async function loadLogs() {
    setLoadingRow('auditTable', 4, 'Loading audit trail…');
    try { state.logs = await api('/verify-logs', {}, true); renderLogs(); }
    catch (error) { state.logs = []; renderLogs(); setLoadingRow('auditTable', 4, error.message); if (error.message.toLowerCase().includes('admin api key')) $('#keyPanel').hidden = false; }
  }
  function updateStats() {
    $('#statStudents').textContent = state.students.length;
    $('#statCredentials').textContent = state.credentials.length;
    $('#statActive').textContent = `${state.credentials.filter(item => item.status === 'active').length} active`;
    $('#statRevoked').textContent = `${state.credentials.filter(item => item.status === 'revoked').length} revoked`;
    $('#statChecks').textContent = state.logs.length;
    $('#studentNavCount').textContent = state.students.length;
    $('#credentialNavCount').textContent = state.credentials.length;
  }
  async function refreshAll() {
    await loadHealth();
    try { state.students = await api('/students', {}, true); } catch (error) { state.students = []; }
    renderStudents();
    try { state.credentials = await api('/credentials', {}, true); } catch (error) { state.credentials = []; }
    renderCredentials();
    try { state.logs = await api('/verify-logs', {}, true); } catch (error) { state.logs = []; }
    renderLogs();
    try { [state.gateLogs, state.gateStatus] = await Promise.all([api('/gate/logs', {}, true), api('/gate/status', {}, true)]); } catch (error) { state.gateLogs = []; state.gateStatus = []; }
    renderGate();
    if (!state.students.length && !state.credentials.length && !state.logs.length) {
      // The protected endpoints may have rejected the key; open settings so it is easy to correct.
      const keyMessage = 'Missing or invalid admin API key';
      if (state.health && state.health.status === 'ok') {
        $('#keyHint').textContent = `If protected lists cannot load, check that the key matches Backend/.env. ${keyMessage}.`;
      }
    }
  }
  function showVerification(data) {
    const result = String(data.result || 'invalid').toLowerCase();
    const safe = ['verified','invalid','revoked'].includes(result) ? result : 'invalid';
    const symbols = {verified:'✓', invalid:'×', revoked:'!' };
    const summaries = {verified:'The proof hash matches an active credential in the database.', invalid:'No credential record matched this proof hash.', revoked:'A matching credential exists, but it has been revoked.'};
    const fields = [ ['Credential title', data.title], ['Type', data.credential_type], ['Issued by', data.issued_by], ['Issued at', data.issued_at ? fmtDate(data.issued_at) : null], ['Checked at', fmtDate(data.checked_at)], ['On the blockchain', data.chain_error ? `Could not check (${data.chain_error})` : (data.on_chain ? (data.on_chain_revoked ? 'Yes — logged, and marked REVOKED on-chain' : 'Yes — logged on-chain, not revoked') : 'Not found on-chain')], ['Proof hash', data.proof_hash] ].filter(pair => pair[1]);
    $('#verifyResult').className = `verify-result result-box-${safe}`;
    $('#verifyResult').innerHTML = `<div class="result-top"><div class="result-symbol">${symbols[safe]}</div><div><div class="result-title">${escapeHtml(result)} credential</div><div class="result-summary">${escapeHtml(summaries[safe])}</div></div></div><div class="result-fields">${fields.map(([label,value]) => `<div class="result-field"><span>${escapeHtml(label)}</span><span>${escapeHtml(value)}</span></div>`).join('')}</div>${data.proof_hash ? `<div style="display:flex;justify-content:flex-end;margin-top:12px"><button class="mini-btn" data-copy-hash="${escapeHtml(data.proof_hash)}" type="button">Copy proof hash</button></div>` : ''}`;
    $('#verifyResult').hidden = false;
  }
  async function verifyHash(hash) {
    const normalized = String(hash || '').trim();
    if (!normalized) { toast('Enter a proof hash first.', 'error'); return; }
    $('#proofHashInput').value = normalized;
    $('#verifyResult').hidden = false;
    $('#verifyResult').className = 'verify-result';
    $('#verifyResult').innerHTML = '<div class="empty-cell">Checking the proof hash…</div>';
    navigate('verify');
    try {
      const data = await api(`/verify/${encodeURIComponent(normalized)}`);
      showVerification(data);
      await loadLogs();
      toast(`Verification result: ${data.result}`, data.result === 'verified' ? 'success' : (data.result === 'invalid' ? 'error' : ''));
    } catch (error) {
      $('#verifyResult').className = 'verify-result result-box-invalid';
      $('#verifyResult').innerHTML = `<div class="result-title">Could not complete verification</div><div class="result-summary">${escapeHtml(error.message)}</div>`;
      toast(error.message, 'error');
    }
  }
  async function copyText(value) {
    try { await navigator.clipboard.writeText(value); toast('Copied full proof hash.', 'success'); }
    catch { const input = document.createElement('textarea'); input.value = value; document.body.appendChild(input); input.select(); const ok = document.execCommand('copy'); input.remove(); toast(ok ? 'Copied full proof hash.' : 'Could not copy. Select the hash manually.', ok ? 'success' : 'error'); }
  }

  $$('.nav-item').forEach(button => button.addEventListener('click', () => navigate(button.dataset.view)));
  $$('[data-go]').forEach(button => button.addEventListener('click', () => navigate(button.dataset.go)));
  $('#keyToggle').addEventListener('click', () => { $('#keyPanel').hidden = !$('#keyPanel').hidden; if (!$('#keyPanel').hidden) $('#adminKeyInput').focus(); });
  $('#saveKeyBtn').addEventListener('click', async () => { state.adminKey = $('#adminKeyInput').value.trim(); sessionStorage.setItem('atlasAdminKey', state.adminKey); state.deviceKey = $('#deviceKeyInput').value.trim(); sessionStorage.setItem('atlasDeviceKey', state.deviceKey); $('#keyHint').textContent = 'Key applied for this browser session. Reloading protected data…'; toast('Admin key applied to this session.', 'success'); await refreshAll(); if (state.view === 'students') loadStudents(); if (state.view === 'credentials') {loadStudents();loadCredentials();} if (state.view === 'audit') loadLogs(); if (state.view === 'gate') loadGate(); });
  $('#studentSearch').addEventListener('input', renderStudents);
  $('#refreshStudents').addEventListener('click', loadStudents);
  $('#refreshCredentials').addEventListener('click', loadCredentials);
  $('#refreshLogs').addEventListener('click', loadLogs);
  $('#refreshGate').addEventListener('click', loadGate);
  $('#simScanForm').addEventListener('submit', event => { event.preventDefault(); simulateScan((event.submitter && event.submitter.dataset.dir) || 'entry'); });

  $('#studentForm').addEventListener('submit', async event => {
    event.preventDefault(); const form = event.currentTarget; const payload = Object.fromEntries(new FormData(form).entries());
    Object.keys(payload).forEach(key => { if (payload[key] === '') payload[key] = null; });
    for (const key of ['student_id','full_name','email']) if (!payload[key]) { setMessage('studentFormMessage', 'Please complete all required fields.', 'error'); return; }
    const submit = $('button[type="submit"]', form); submit.disabled = true; submit.textContent = 'Creating record…';
    try { const student = await api('/students', {method:'POST', body:JSON.stringify(payload)}, true); form.reset(); setMessage('studentFormMessage', `Student ${student.student_id} was created successfully.`, 'success'); toast('Student record created.', 'success'); await loadStudents(); }
    catch (error) { setMessage('studentFormMessage', error.message, 'error'); toast(error.message, 'error'); if (error.message.toLowerCase().includes('admin api key')) $('#keyPanel').hidden = false; }
    finally { submit.disabled = false; submit.innerHTML = 'Create student record <span>→</span>'; }
  });

  $('#credentialForm').addEventListener('submit', async event => {
    event.preventDefault(); const form = event.currentTarget; const payload = Object.fromEntries(new FormData(form).entries());
    for (const key of ['student_id','credential_type','title','issued_by']) if (!payload[key]) { setMessage('credentialFormMessage', 'Please complete all required fields.', 'error'); return; }
    const submit = $('button[type="submit"]', form); submit.disabled = true; submit.textContent = 'Issuing…';
    try { const credential = await api('/credentials', {method:'POST', body:JSON.stringify(payload)}, true); form.reset(); setMessage('credentialFormMessage', `Credential issued. Proof hash: ${credential.proof_hash}`, 'success'); toast('Credential issued and proof hash generated.', 'success'); await loadCredentials(); await loadLogs();
      // Keep the newly-created proof one click away from the verification screen.
      const message = $('#credentialFormMessage'); const action = document.createElement('button'); action.className='mini-btn'; action.type='button'; action.textContent='Verify this credential'; action.style.marginLeft='8px'; action.addEventListener('click',()=>verifyHash(credential.proof_hash)); message.appendChild(action);
    } catch (error) { setMessage('credentialFormMessage', error.message, 'error'); toast(error.message, 'error'); if (error.message.toLowerCase().includes('admin api key')) $('#keyPanel').hidden = false; }
    finally { submit.disabled = false; submit.innerHTML = 'Issue credential <span>→</span>'; }
  });

  $('#verifyForm').addEventListener('submit', event => { event.preventDefault(); verifyHash(new FormData(event.currentTarget).get('proof_hash')); });
  document.addEventListener('click', async event => {
    const detailButton = event.target.closest('[data-student-details]');
    if (detailButton) {
      const id = detailButton.dataset.studentDetails;
      try { const student = await api(`/students/${encodeURIComponent(id)}`, {}, true); alert(`Student details\n\nName: ${student.full_name}\nStudent ID: ${student.student_id}\nEmail: ${student.email}\nPhone: ${student.phone || '—'}\nCourse: ${student.course || '—'}\nHostel: ${student.hostel || '—'}\nRFID UID: ${student.rfid_uid || '—'}\nOn campus: ${student.inside ? 'yes' : 'no'}\nCreated: ${fmtDate(student.created_at)}`); }
      catch (error) { toast(error.message, 'error'); }
      return;
    }
    const credentialDetailButton = event.target.closest('[data-credential-details]');
    if (credentialDetailButton) {
      try {
        const credential = await api(`/credentials/${encodeURIComponent(credentialDetailButton.dataset.credentialDetails)}`, {}, true);
        alert(`Credential details\n\nTitle: ${credential.title}\nType: ${credential.credential_type}\nStudent ID: ${credential.student_id}\nIssued by: ${credential.issued_by}\nStatus: ${credential.status}\nIssued: ${fmtDate(credential.issued_at)}\nRevoked: ${fmtDate(credential.revoked_at)}\n\nProof hash:\n${credential.proof_hash}`);
      } catch (error) { toast(error.message, 'error'); }
      return;
    }
    const copyButton = event.target.closest('[data-copy-hash]');
    if (copyButton) { await copyText(copyButton.dataset.copyHash); return; }
    const verifyButton = event.target.closest('[data-verify-hash]');
    if (verifyButton) { verifyHash(verifyButton.dataset.verifyHash); return; }
    const revokeButton = event.target.closest('[data-revoke]');
    if (revokeButton) {
      const id = revokeButton.dataset.revoke; const title = revokeButton.dataset.title || 'this credential';
      if (!window.confirm(`Revoke “${title}”? This marks it revoked in the database and on the blockchain.`)) return;
      revokeButton.disabled = true;
      try { await api(`/credentials/${encodeURIComponent(id)}/revoke`, {method:'POST'}, true); toast('Credential revoked.', 'success'); await loadCredentials(); await loadLogs(); }
      catch (error) { toast(error.message, 'error'); revokeButton.disabled = false; }
    }
  });

  // Initial state: health is public; protected endpoints use the admin key above.
  refreshAll();
})();
