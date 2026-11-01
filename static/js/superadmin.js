const today = new Date().toISOString().split('T')[0];

function showSection(name, event) {
  document.querySelectorAll('.section').forEach(s => s.classList.remove('active'));
  document.querySelectorAll('.nav-item').forEach(i => i.classList.remove('active'));
  document.getElementById('section-' + name).classList.add('active');
  if (event && event.currentTarget) event.currentTarget.classList.add('active');
  if (name === 'payments') loadPayments();
}

let superPlans = {};

async function initPage() {
  const r = await fetch('/api/session');
  const d = await r.json();
  if (d.type !== 'superadmin') { window.location.href = '/'; return; }
  document.getElementById('nav-user').textContent = d.name;
  await loadPlans();
  loadDashboard();
  loadSchools();
  loadPayments();
}

async function loadPlans() {
  const r = await fetch('/api/schools/plans');
  superPlans = await r.json();
  const select = document.getElementById('edit-school-plan');
  if (!select) return;
  select.innerHTML = Object.keys(superPlans).map(key => `
    <option value="${key}">${superPlans[key].name}</option>
  `).join('');
}

async function logout() {
  await fetch('/api/auth/logout', { method: 'POST' });
  window.location.href = '/';
}

async function loadDashboard() {
  const r = await fetch('/api/super/dashboard');
  const d = await r.json();
  const grid = document.getElementById('summary-grid');
  grid.innerHTML = `
    <div class="summary-card">
      <h3>Total Schools</h3>
      <p>${d.summary.total_schools}</p>
    </div>
    <div class="summary-card">
      <h3>Active Schools</h3>
      <p>${d.summary.active_schools}</p>
    </div>
    <div class="summary-card">
      <h3>Trial Schools</h3>
      <p>${d.summary.trial_schools}</p>
    </div>
    <div class="summary-card">
      <h3>Pending Payments</h3>
      <p>${d.summary.pending_payments}</p>
    </div>
    <div class="summary-card">
      <h3>Total Teachers</h3>
      <p>${d.summary.total_teachers}</p>
    </div>
    <div class="summary-card">
      <h3>School Admins</h3>
      <p>${d.summary.total_school_admins}</p>
    </div>
  `;
}

async function loadSchools() {
  const r = await fetch('/api/super/schools');
  const schools = await r.json();
  const body = document.getElementById('schools-body');
  body.innerHTML = schools.map(s => `
    <tr>
      <td>${s.name}</td>
      <td><code>${s.code}</code></td>
      <td>${s.plan}</td>
      <td>${s.is_active ? '<span class="status-verified">Active</span>' : '<span class="status-pending">Inactive</span>'}</td>
      <td>${s.trial_ends_at || '—'}</td>
      <td><button class="btn-sm btn-edit" onclick='openEditSchool(${JSON.stringify(s)})'>Edit</button></td>
    </tr>
  `).join('');
}

function openEditSchool(school) {
  document.getElementById('edit-school-id').value = school.id;
  document.getElementById('edit-school-name').value = school.name;
  document.getElementById('edit-school-plan').value = school.plan;
  document.getElementById('edit-school-link').value = school.public_link || '';
  document.getElementById('edit-school-link-label').value = school.link_label || 'Weekly School Transport Link';
  document.getElementById('edit-school-active').checked = school.is_active;
  document.getElementById('edit-school-plan').dispatchEvent(new Event('change'));
  openModal('school-modal');
}

async function loadPayments() {
  const r = await fetch('/api/super/payments');
  const payments = await r.json();
  const body = document.getElementById('super-payments-body');
  body.innerHTML = payments.length ? payments.map(p => `
    <tr>
      <td>${p.school_name}</td>
      <td><code>${p.school_code}</code></td>
      <td>${p.amount.toFixed(2)} ${p.currency}</td>
      <td>${p.mpesa_phone}</td>
      <td>${p.transaction_code}</td>
      <td>${new Date(p.created_at).toLocaleString()}</td>
      <td style="display:flex;gap:0.4rem;flex-wrap:wrap">
        <button class="btn-sm btn-edit" onclick="verifyPayment(${p.id}, 'verified')">Verify</button>
        <button class="btn-sm btn-del" onclick="verifyPayment(${p.id}, 'rejected')">Reject</button>
      </td>
    </tr>
  `).join('') : '<tr><td colspan="7" class="muted" style="text-align:center;padding:1rem">No pending payments.</td></tr>';
}

async function saveSchool() {
  const id = document.getElementById('edit-school-id').value;
  const name = document.getElementById('edit-school-name').value.trim();
  const plan = document.getElementById('edit-school-plan').value;
  const public_link = document.getElementById('edit-school-link').value.trim();
  const link_label = document.getElementById('edit-school-link-label').value.trim();
  const is_active = document.getElementById('edit-school-active').checked;

  if (!name) {
    alert('School name is required.');
    return;
  }

  const r = await fetch('/api/super/schools/' + id, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name, plan, public_link, link_label, is_active })
  });
  const d = await r.json();
  if (d.success) {
    closeModal('school-modal');
    loadSchools();
    loadDashboard();
  } else {
    alert(d.message || 'Unable to save school details.');
  }
}

async function verifyPayment(paymentId, status) {
  const r = await fetch('/api/payments/verify', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ payment_id: paymentId, status })
  });
  const d = await r.json();
  if (d.success) {
    loadPayments();
    loadDashboard();
  } else {
    alert(d.message || 'Unable to update payment status.');
  }
}

function openModal(id) {
  document.getElementById(id).classList.remove('hidden');
}

function closeModal(id) {
  document.getElementById(id).classList.add('hidden');
}

initPage();
