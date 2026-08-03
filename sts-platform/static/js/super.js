async function init() {
  const r = await fetch('/api/session');
  const d = await r.json();
  if (d.type !== 'super') { window.location.href = '/'; return; }
  document.getElementById('nav-user').textContent = d.name;
  loadAll();
}

function showSection(name, el) {
  document.querySelectorAll('.section').forEach(s => s.classList.remove('active'));
  document.querySelectorAll('.nav-item').forEach(i => i.classList.remove('active'));
  document.getElementById('section-' + name).classList.add('active');
  if (el) el.classList.add('active');
  if (name === 'schools')   loadSchools();
  if (name === 'payments')  loadPayments();
  if (name === 'logs')      loadLogs();
  if (name === 'dashboard') loadAll();
  if (name === 'settings')  loadSettings();
}

function openModal(id)  { document.getElementById(id).classList.remove('hidden'); }
function closeModal(id) { document.getElementById(id).classList.add('hidden'); }

// ── DASHBOARD ─────────────────────────
async function loadAll() {
  const r = await fetch('/api/super/stats');
  const d = await r.json();
  document.getElementById('stats-grid').innerHTML = `
    <div class="stat-card"><div class="stat-value" style="color:var(--sky)">${d.total_schools}</div><div class="stat-label">Total Schools</div></div>
    <div class="stat-card"><div class="stat-value" style="color:var(--success)">${d.active}</div><div class="stat-label">Active</div></div>
    <div class="stat-card"><div class="stat-value" style="color:var(--warn)">${d.trial}</div><div class="stat-label">On Trial</div></div>
    <div class="stat-card"><div class="stat-value" style="color:var(--red)">${d.expired}</div><div class="stat-label">Expired</div></div>
    <div class="stat-card"><div class="stat-value" style="color:var(--success)">KES ${d.total_revenue.toLocaleString()}</div><div class="stat-label">Total Revenue</div></div>
    <div class="stat-card"><div class="stat-value" style="color:var(--warn)">${d.pending_payments}</div><div class="stat-label">Pending Payments</div></div>
    <div class="stat-card"><div class="stat-value" style="color:var(--sky)">${d.total_teachers}</div><div class="stat-label">Total Teachers</div></div>
  `;
  const pending = document.getElementById('pending-alert');
  if (d.pending_payments > 0) {
    pending.style.display = 'block';
    document.getElementById('pending-count').textContent = d.pending_payments;
  } else {
    pending.style.display = 'none';
  }
}

// ── SCHOOLS ───────────────────────────
async function loadSchools() {
  const r = await fetch('/api/super/schools');
  const data = await r.json();
  const statusBadge = s => ({
    active:    '<span class="badge-green">Active</span>',
    trial:     '<span class="badge-warn">Trial</span>',
    expired:   '<span class="badge-grey">Expired</span>',
    suspended: '<span class="badge-grey">Suspended</span>'
  }[s] || `<span class="badge-grey">${s}</span>`);

  document.getElementById('schools-body').innerHTML = data.length ? data.map(s => `
    <tr>
      <td><strong>${s.name}</strong><br/><small style="color:var(--muted)">${s.county || '—'}</small></td>
      <td><code>${s.code}</code></td>
      <td><span class="badge-sky">${s.plan}</span></td>
      <td>${statusBadge(s.status)}</td>
      <td>${s.days_remaining} days</td>
      <td>${s.teachers}</td>
      <td>${s.routes}</td>
      <td>
        <div style="display:flex;gap:.3rem;flex-wrap:wrap">
          <button class="btn-sm btn-edit"    onclick="openEditSchool(${JSON.stringify(s).replace(/"/g,'&quot;')})">✏️ Edit</button>
          <button class="btn-sm btn-success" onclick="openActivate(${s.id},'${s.name}')">✅ Activate</button>
          <button class="btn-sm btn-warn"    onclick="openResetPw(${s.id},'${s.name}')">🔑 Reset PW</button>
          <button class="btn-sm btn-del"     onclick="deleteSchool(${s.id},'${s.name}')">🗑️ Delete</button>
        </div>
      </td>
    </tr>`).join('')
  : '<tr><td colspan="8" style="text-align:center;color:var(--muted);padding:2rem">No schools yet. Create one above.</td></tr>';
}

// ── CREATE SCHOOL ─────────────────────
function openCreateSchool() {
  ['cs-name','cs-code','cs-county','cs-phone','cs-email','cs-admin','cs-pw'].forEach(id => {
    document.getElementById(id).value = '';
  });
  document.getElementById('cs-plan').value = 'basic';
  document.getElementById('cs-days').value = '30';
  document.getElementById('cs-err').classList.add('hidden');
  openModal('create-school-modal');
}

async function createSchool() {
  const name           = document.getElementById('cs-name').value.trim();
  const code           = document.getElementById('cs-code').value.trim().toUpperCase();
  const county         = document.getElementById('cs-county').value.trim();
  const phone          = document.getElementById('cs-phone').value.trim();
  const email          = document.getElementById('cs-email').value.trim();
  const plan           = document.getElementById('cs-plan').value;
  const days           = document.getElementById('cs-days').value;
  const admin_username = document.getElementById('cs-admin').value.trim();
  const admin_password = document.getElementById('cs-pw').value;
  const err            = document.getElementById('cs-err');
  err.classList.add('hidden');

  if (!name || !code || !admin_username || !admin_password) {
    err.textContent = 'School name, code, admin username and password are required.';
    err.classList.remove('hidden'); return;
  }
  if (admin_password.length < 6) {
    err.textContent = 'Password must be at least 6 characters.';
    err.classList.remove('hidden'); return;
  }

  const r = await fetch('/api/super/school/create', {
    method: 'POST', headers: {'Content-Type':'application/json'},
    body: JSON.stringify({name, code, county, phone, email, plan, days: parseInt(days), admin_username, admin_password})
  });
  const d = await r.json();
  if (d.success) {
    closeModal('create-school-modal');
    loadSchools(); loadAll();
    alert('✅ ' + d.message);
  } else {
    err.textContent = d.error || 'Failed to create school.';
    err.classList.remove('hidden');
  }
}

// ── EDIT SCHOOL ───────────────────────
function openEditSchool(s) {
  document.getElementById('es-id').value        = s.id;
  document.getElementById('es-name').value      = s.name;
  document.getElementById('es-county').value    = s.county || '';
  document.getElementById('es-phone').value     = s.phone  || '';
  document.getElementById('es-email').value     = s.email  || '';
  document.getElementById('es-plan').value      = s.plan;
  document.getElementById('es-status').value    = s.status;
  document.getElementById('es-subend').value    = s.subscription_end || '';
  document.getElementById('es-err').classList.add('hidden');
  openModal('edit-school-modal');
}

async function saveEditSchool() {
  const id     = document.getElementById('es-id').value;
  const err    = document.getElementById('es-err');
  err.classList.add('hidden');
  const body = {
    name:             document.getElementById('es-name').value.trim(),
    county:           document.getElementById('es-county').value.trim(),
    phone:            document.getElementById('es-phone').value.trim(),
    email:            document.getElementById('es-email').value.trim(),
    plan:             document.getElementById('es-plan').value,
    status:           document.getElementById('es-status').value,
    subscription_end: document.getElementById('es-subend').value,
  };
  if (!body.name) { err.textContent='School name is required.'; err.classList.remove('hidden'); return; }

  const r = await fetch(`/api/super/school/${id}/edit`, {
    method: 'PUT', headers: {'Content-Type':'application/json'},
    body: JSON.stringify(body)
  });
  const d = await r.json();
  if (d.success) { closeModal('edit-school-modal'); loadSchools(); loadAll(); }
  else { err.textContent = d.error || 'Failed to save.'; err.classList.remove('hidden'); }
}

// ── ACTIVATE SCHOOL ───────────────────
function openActivate(id, name) {
  document.getElementById('activate-school-id').value   = id;
  document.getElementById('activate-school-name').value = name;
  openModal('activate-modal');
}

async function activateSchool() {
  const id   = document.getElementById('activate-school-id').value;
  const days = document.getElementById('activate-days').value;
  const r = await fetch(`/api/super/school/${id}/activate`, {
    method: 'POST', headers: {'Content-Type':'application/json'},
    body: JSON.stringify({days: parseInt(days)})
  });
  const d = await r.json();
  if (d.success) { closeModal('activate-modal'); loadSchools(); loadAll(); alert('✅ School activated!'); }
}

// ── SUSPEND ───────────────────────────
async function suspendSchool(id, name) {
  if (!confirm(`Suspend ${name}? They will lose access immediately.`)) return;
  await fetch(`/api/super/school/${id}/suspend`, {method:'POST'});
  loadSchools(); loadAll();
}

// ── RESET ADMIN PASSWORD ──────────────
function openResetPw(id, name) {
  document.getElementById('rp-id').value          = id;
  document.getElementById('rp-school-name').value = name;
  document.getElementById('rp-pw').value          = '';
  document.getElementById('rp-pw2').value         = '';
  document.getElementById('rp-err').classList.add('hidden');
  openModal('reset-pw-modal');
}

async function resetPassword() {
  const id  = document.getElementById('rp-id').value;
  const pw  = document.getElementById('rp-pw').value;
  const pw2 = document.getElementById('rp-pw2').value;
  const err = document.getElementById('rp-err');
  err.classList.add('hidden');

  if (pw.length < 6) { err.textContent='Password must be at least 6 characters.'; err.classList.remove('hidden'); return; }
  if (pw !== pw2)    { err.textContent='Passwords do not match.'; err.classList.remove('hidden'); return; }

  const r = await fetch(`/api/super/school/${id}/reset-password`, {
    method: 'POST', headers: {'Content-Type':'application/json'},
    body: JSON.stringify({password: pw})
  });
  const d = await r.json();
  if (d.success) { closeModal('reset-pw-modal'); alert('✅ ' + d.message); }
  else { err.textContent = d.error || 'Failed to reset password.'; err.classList.remove('hidden'); }
}

// ── DELETE SCHOOL ─────────────────────
async function deleteSchool(id, name) {
  if (!confirm(`⚠️ DELETE "${name}"?\n\nThis will permanently remove the school, all teachers, routes, rosters, and payment history.\n\nThis cannot be undone.`)) return;
  if (!confirm(`Are you absolutely sure you want to delete "${name}"?`)) return;
  const r = await fetch(`/api/super/school/${id}/delete`, {method:'DELETE'});
  const d = await r.json();
  if (d.success) { loadSchools(); loadAll(); alert(`${name} has been deleted.`); }
  else alert('Delete failed: ' + (d.error || 'Unknown error'));
}

// ── PAYMENTS ──────────────────────────
async function loadPayments() {
  const r = await fetch('/api/super/payments');
  const data = await r.json();
  const statusBadge = s => ({
    pending:  '<span class="badge-warn">Pending</span>',
    verified: '<span class="badge-green">Verified</span>',
    rejected: '<span class="badge-grey">Rejected</span>'
  }[s] || s);

  document.getElementById('payments-body').innerHTML = data.length ? data.map(p => `
    <tr>
      <td><strong>${p.school}</strong></td>
      <td><code>${p.mpesa_code}</code></td>
      <td><strong>KES ${p.amount.toLocaleString()}</strong></td>
      <td>${p.plan}</td>
      <td>${p.phone || '—'}</td>
      <td>${statusBadge(p.status)}</td>
      <td style="font-size:.8rem">${p.submitted_at}</td>
      <td style="display:flex;gap:.3rem">
        ${p.status === 'pending' ? `
          <button class="btn-sm btn-success" onclick="verifyPayment(${p.id})">✅ Verify</button>
          <button class="btn-sm btn-del"     onclick="rejectPayment(${p.id})">✗ Reject</button>
        ` : '—'}
      </td>
    </tr>`).join('')
  : '<tr><td colspan="8" style="text-align:center;color:var(--muted);padding:2rem">No payments yet.</td></tr>';
}

async function verifyPayment(id) {
  if (!confirm('Verify this payment and activate the school?')) return;
  const r = await fetch(`/api/super/payment/${id}/verify`, {method:'POST'});
  const d = await r.json();
  if (d.success) { alert('✅ ' + d.message); loadPayments(); loadAll(); }
}

async function rejectPayment(id) {
  if (!confirm('Reject this payment?')) return;
  await fetch(`/api/super/payment/${id}/reject`, {method:'POST'});
  loadPayments();
}

// ── LOGS ──────────────────────────────
async function loadLogs() {
  const r = await fetch('/api/super/logs');
  const data = await r.json();
  document.getElementById('logs-body').innerHTML = data.length ? data.map(l => `
    <tr>
      <td style="white-space:nowrap;font-size:.82rem">${l.time}</td>
      <td><span class="badge-${l.user_type==='super'?'sky':l.user_type==='admin'?'red':'grey'}">${l.user_type}</span></td>
      <td>${l.user_name}</td>
      <td style="font-size:.85rem">${l.action}</td>
      <td style="color:var(--muted);font-size:.8rem">${l.ip}</td>
    </tr>`).join('')
  : '<tr><td colspan="5" style="text-align:center;color:var(--muted);padding:2rem">No logs yet.</td></tr>';
}

// ── SETTINGS ──────────────────────────
async function loadSettings() {
  const r = await fetch('/api/super/settings');
  const d = await r.json();
  if (d.error) return;
  document.getElementById('set-mpesa-number').value  = d.mpesa_number  || '';
  document.getElementById('set-mpesa-name').value    = d.mpesa_name    || '';
  document.getElementById('set-platform-name').value = d.platform_name || '';
  document.getElementById('set-trial-days').value    = d.trial_days    || 30;
  if (d.updated_at) {
    document.getElementById('set-updated').textContent = `Last updated: ${d.updated_at}`;
  }
}

async function saveSettings() {
  const err = document.getElementById('set-err');
  err.classList.add('hidden');
  const mpesa_number  = document.getElementById('set-mpesa-number').value.trim();
  const mpesa_name    = document.getElementById('set-mpesa-name').value.trim();
  const platform_name = document.getElementById('set-platform-name').value.trim();
  const trial_days    = parseInt(document.getElementById('set-trial-days').value) || 30;

  if (!mpesa_number || !mpesa_name) {
    err.textContent = 'M-Pesa number and name are required.';
    err.classList.remove('hidden'); return;
  }
  const r = await fetch('/api/super/settings', {
    method: 'PUT', headers: {'Content-Type':'application/json'},
    body: JSON.stringify({mpesa_number, mpesa_name, platform_name, trial_days})
  });
  const d = await r.json();
  if (d.success) {
    document.getElementById('set-updated').textContent = `✅ ${d.message}`;
  } else {
    err.textContent = d.error || 'Failed to save settings.';
    err.classList.remove('hidden');
  }
}

// ── LOGOUT ────────────────────────────
async function logout() {
  await fetch('/api/logout', {method:'POST'});
  window.location.href = '/';
}

init();
