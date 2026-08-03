async function init() {
  const r = await fetch('/api/session');
  const d = await r.json();
  if (d.type !== 'super') { window.location.href = '/'; return; }
  document.getElementById('nav-user').textContent = d.name;
  loadAll();
}

function showSection(name, el) {
  document.querySelectorAll('.section').forEach(s=>s.classList.remove('active'));
  document.querySelectorAll('.nav-item').forEach(i=>i.classList.remove('active'));
  document.getElementById('section-'+name).classList.add('active');
  if(el) el.classList.add('active');
  if(name==='schools') loadSchools();
  if(name==='payments') loadPayments();
  if(name==='logs') loadLogs();
}

function openModal(id){document.getElementById(id).classList.remove('hidden');}
function closeModal(id){document.getElementById(id).classList.add('hidden');}

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
  const pc = document.getElementById('pending-count');
  if (d.pending_payments > 0) {
    pending.style.display = 'block';
    pc.textContent = d.pending_payments;
  } else {
    pending.style.display = 'none';
  }
}

async function loadSchools() {
  const r = await fetch('/api/super/schools');
  const data = await r.json();
  const statusBadge = s => ({
    active:'<span class="badge-green">Active</span>',
    trial:'<span class="badge-warn">Trial</span>',
    expired:'<span class="badge-grey">Expired</span>',
    suspended:'<span class="badge-grey">Suspended</span>'
  }[s] || s);
  document.getElementById('schools-body').innerHTML = data.map(s => `
    <tr>
      <td><strong>${s.name}</strong><br/><small style="color:var(--muted)">${s.county||''}</small></td>
      <td><code>${s.code}</code></td>
      <td>${s.plan}</td>
      <td>${statusBadge(s.status)}</td>
      <td>${s.days_remaining} days</td>
      <td>${s.teachers}</td>
      <td>${s.routes}</td>
      <td style="display:flex;gap:.3rem;flex-wrap:wrap">
        <button class="btn-sm btn-edit" onclick="openActivate(${s.id},'${s.name}')">Activate</button>
        <button class="btn-sm btn-del" onclick="suspendSchool(${s.id},'${s.name}')">Suspend</button>
      </td>
    </tr>`).join('');
}

function openActivate(id, name) {
  document.getElementById('activate-school-id').value = id;
  document.getElementById('activate-school-name').value = name;
  openModal('activate-modal');
}

async function activateSchool() {
  const id = document.getElementById('activate-school-id').value;
  const days = document.getElementById('activate-days').value;
  const r = await fetch(`/api/super/school/${id}/activate`, {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({days: parseInt(days)})});
  const d = await r.json();
  if(d.success) { closeModal('activate-modal'); loadSchools(); loadAll(); alert('School activated successfully!'); }
}

async function suspendSchool(id, name) {
  if(!confirm(`Suspend ${name}? They will lose access immediately.`)) return;
  await fetch(`/api/super/school/${id}/suspend`, {method:'POST'});
  loadSchools();
}

async function loadPayments() {
  const r = await fetch('/api/super/payments');
  const data = await r.json();
  const statusBadge = s => ({
    pending:'<span class="badge-warn">Pending</span>',
    verified:'<span class="badge-green">Verified</span>',
    rejected:'<span class="badge-grey">Rejected</span>'
  }[s] || s);
  document.getElementById('payments-body').innerHTML = data.map(p => `
    <tr>
      <td><strong>${p.school}</strong></td>
      <td><code>${p.mpesa_code}</code></td>
      <td><strong>KES ${p.amount.toLocaleString()}</strong></td>
      <td>${p.plan}</td>
      <td>${p.phone||'—'}</td>
      <td>${statusBadge(p.status)}</td>
      <td style="font-size:.8rem">${p.submitted_at}</td>
      <td style="display:flex;gap:.3rem">
        ${p.status==='pending' ? `
          <button class="btn-sm btn-success" onclick="verifyPayment(${p.id})">✅ Verify</button>
          <button class="btn-sm btn-del" onclick="rejectPayment(${p.id})">✗ Reject</button>
        ` : '—'}
      </td>
    </tr>`).join('') || '<tr><td colspan="8" style="text-align:center;color:var(--muted);padding:1rem">No payments yet.</td></tr>';
}

async function verifyPayment(id) {
  if(!confirm('Verify this payment and activate the school?')) return;
  const r = await fetch(`/api/super/payment/${id}/verify`, {method:'POST'});
  const d = await r.json();
  if(d.success) { alert('✅ Payment verified! ' + d.message); loadPayments(); loadAll(); }
}

async function rejectPayment(id) {
  if(!confirm('Reject this payment?')) return;
  await fetch(`/api/super/payment/${id}/reject`, {method:'POST'});
  loadPayments();
}

async function loadLogs() {
  const r = await fetch('/api/super/logs');
  const data = await r.json();
  document.getElementById('logs-body').innerHTML = data.map(l => `
    <tr>
      <td style="white-space:nowrap;font-size:.82rem">${l.time}</td>
      <td><span class="badge-${l.user_type==='super'?'sky':l.user_type==='admin'?'red':'grey'}">${l.user_type}</span></td>
      <td>${l.user_name}</td>
      <td style="font-size:.85rem">${l.action}</td>
      <td style="color:var(--muted);font-size:.8rem">${l.ip}</td>
    </tr>`).join('');
}

async function logout() {
  await fetch('/api/logout', {method:'POST'});
  window.location.href = '/';
}

init();
