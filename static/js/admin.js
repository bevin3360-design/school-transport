// ─────────────────────────────────────────
// SCHOOL TRANSPORT SYSTEM – Admin JS
// ─────────────────────────────────────────

const today = new Date().toISOString().split('T')[0];
document.getElementById('roster-date').value = today;

// ── SECTION NAVIGATION ──
function showSection(name) {
  document.querySelectorAll('.section').forEach(s => s.classList.remove('active'));
  document.querySelectorAll('.nav-item').forEach(i => i.classList.remove('active'));
  document.getElementById('section-' + name).classList.add('active');
  event.currentTarget.classList.add('active');

  if (name === 'roster') { loadRoster(); loadWeekGrid(); }
  if (name === 'teachers') loadTeachers();
  if (name === 'routes') loadRoutes();
  if (name === 'logs') loadLogs();
  if (name === 'admins') loadAdmins();
  if (name === 'settings') loadSettings();
}

// ── MODALS ──
function openModal(id) {
  document.getElementById(id).classList.remove('hidden');
}
function closeModal(id) {
  document.getElementById(id).classList.add('hidden');
}

// ── SESSION & INIT ──
async function initPage() {
  const r = await fetch('/api/session');
  const d = await r.json();
  if (d.type !== 'admin') { window.location.href = '/'; return; }
  document.getElementById('nav-user').textContent = d.name;
  document.getElementById('nav-role').textContent = d.role;
  loadSettings();
  loadRoster();
  loadWeekGrid();
}

async function logout() {
  await fetch('/api/logout', { method: 'POST' });
  window.location.href = '/';
}

// ── SETTINGS ──
async function loadSettings() {
  const r = await fetch('/api/settings');
  const d = await r.json();
  document.getElementById('nav-school-name').textContent = d.school_name + ' – Transport System';
  document.title = d.school_name + ' Admin';
  const sn = document.getElementById('setting-school-name');
  const sm = document.getElementById('setting-morning');
  if (sn) sn.value = d.school_name;
  if (sm) sm.checked = d.morning_route_active;
}

async function saveSettings() {
  const school_name = document.getElementById('setting-school-name').value.trim();
  const morning_route_active = document.getElementById('setting-morning').checked;
  const r = await fetch('/api/settings', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ school_name, morning_route_active })
  });
  const d = await r.json();
  const msg = document.getElementById('settings-msg');
  if (d.success) {
    msg.classList.remove('hidden');
    document.getElementById('nav-school-name').textContent = school_name + ' – Transport System';
    setTimeout(() => msg.classList.add('hidden'), 3000);
  }
}

// ── ROSTER ──
async function loadRoster() {
  const dateVal = document.getElementById('roster-date').value || today;
  const r = await fetch('/api/roster?date=' + dateVal);
  const data = await r.json();

  const tbody = document.getElementById('roster-body');
  const tableWrap = document.getElementById('roster-table-wrap');
  const emptyMsg = document.getElementById('roster-empty-msg');
  const wkMsg = document.getElementById('roster-weekend-msg');

  wkMsg.classList.add('hidden');
  emptyMsg.classList.add('hidden');
  tableWrap.style.display = 'block';

  const d = new Date(dateVal + 'T12:00:00');
  const dow = d.getDay();
  if (dow === 0 || dow === 6) {
    wkMsg.classList.remove('hidden');
    tableWrap.style.display = 'none';
    tbody.innerHTML = '';
    return;
  }

  if (!data.length) {
    emptyMsg.classList.remove('hidden');
    tableWrap.style.display = 'none';
    tbody.innerHTML = '';
    return;
  }

  tbody.innerHTML = data.map((a, i) => `
    <tr>
      <td>${i + 1}</td>
      <td><strong>${a.teacher_name}</strong></td>
      <td><code>${a.teaching_code}</code></td>
      <td>${a.route_name}</td>
      <td>${a.is_morning ? '🌅 Morning' : '🚌 Afternoon'}</td>
      <td><span class="status-${a.status}">${a.status.toUpperCase()}</span></td>
      <td>
        ${a.status !== 'absent' ? `<button class="btn-sm btn-absent" onclick="markAbsent(${a.id})">Mark Absent</button>` : `<button class="btn-sm btn-edit" onclick="loadReplacements(${a.id})">Replace</button>`}
      </td>
    </tr>
  `).join('');
}

async function generateRoster() {
  const dateVal = document.getElementById('roster-date').value || today;
  const r = await fetch('/api/roster/generate', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ date: dateVal })
  });
  const d = await r.json();
  if (d.error) {
    alert(d.error);
  } else {
    loadRoster();
    loadWeekGrid();
  }
}

async function loadWeekGrid() {
  // Find Monday of current week
  const d = new Date();
  const day = d.getDay();
  const diff = d.getDate() - day + (day === 0 ? -6 : 1);
  const monday = new Date(d.setDate(diff));
  const start = monday.toISOString().split('T')[0];

  const r = await fetch('/api/roster/week?start=' + start);
  const days = await r.json();
  const grid = document.getElementById('week-grid');
  if (!days.length) { grid.innerHTML = '<p class="muted">No data yet for this week.</p>'; return; }

  grid.innerHTML = days.map(day => `
    <div class="week-day-card">
      <div class="week-day-header">${day.day} <small style="font-weight:400;opacity:0.7">${day.date}</small></div>
      <div class="week-day-body">
        ${day.assignments.length
          ? day.assignments.map(a => `
              <div class="week-assignment ${a.is_morning ? 'morning' : ''}">
                <strong>${a.teacher_name}</strong><br/>
                <small>${a.route_name}</small>
              </div>`).join('')
          : '<p class="muted" style="font-size:0.8rem">No roster generated</p>'}
      </div>
    </div>
  `).join('');
}

async function markAbsent(assignmentId) {
  if (!confirm('Mark this teacher as absent?')) return;
  const r = await fetch('/api/roster/' + assignmentId + '/absent', { method: 'POST' });
  const d = await r.json();
  if (d.success) {
    loadRoster();
    if (d.suggestions && d.suggestions.length) {
      showReplacements(assignmentId, d.suggestions);
    } else {
      alert('Marked absent. No replacement suggestions available.');
    }
  }
}

async function loadReplacements(assignmentId) {
  const r = await fetch('/api/roster/' + assignmentId + '/absent', { method: 'POST' });
  const d = await r.json();
  if (d.suggestions) showReplacements(assignmentId, d.suggestions);
}

function showReplacements(assignmentId, suggestions) {
  document.getElementById('replace-assignment-id').value = assignmentId;
  const list = document.getElementById('replace-list');
  if (!suggestions.length) {
    list.innerHTML = '<p class="muted">No available replacements.</p>';
  } else {
    list.innerHTML = suggestions.map(s => `
      <div class="replace-item">
        <span>${s.name} <small style="color:#7F8C8D">(${s.teaching_code})</small></span>
        <button class="btn-sm btn-edit" onclick="confirmReplace(${assignmentId}, ${s.id})">Assign</button>
      </div>
    `).join('');
  }
  openModal('replace-modal');
}

async function confirmReplace(assignmentId, teacherId) {
  const r = await fetch('/api/roster/' + assignmentId + '/replace', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ teacher_id: teacherId })
  });
  const d = await r.json();
  if (d.success) {
    closeModal('replace-modal');
    loadRoster();
  }
}

// ── TEACHERS ──
async function loadTeachers() {
  const r = await fetch('/api/teachers');
  const data = await r.json();
  document.getElementById('teachers-body').innerHTML = data.map(t => `
    <tr>
      <td><strong>${t.name}</strong></td>
      <td><code>${t.teaching_code}</code></td>
      <td>••••</td>
      <td>${t.authorised
        ? '<span style="color:var(--success)">✔ Yes</span>'
        : '<span style="color:var(--red)">✘ No</span>'}</td>
      <td>${t.active
        ? '<span style="color:var(--success)">Active</span>'
        : '<span style="color:var(--text-light)">Inactive</span>'}</td>
      <td style="display:flex;gap:0.4rem;flex-wrap:wrap">
        <button class="btn-sm btn-edit" onclick='editTeacher(${JSON.stringify(t)})'>Edit</button>
        <button class="btn-sm btn-del" onclick="deleteTeacher(${t.id})">Delete</button>
      </td>
    </tr>
  `).join('');
}

function openAddTeacher() {
  document.getElementById('teacher-modal-title').textContent = 'Add Teacher';
  document.getElementById('edit-teacher-id').value = '';
  document.getElementById('t-name').value = '';
  document.getElementById('t-tcode').value = '';
  document.getElementById('t-pcode').value = '';
  document.getElementById('t-auth').checked = false;
  document.getElementById('t-active').checked = true;
  openModal('teacher-modal');
}

function editTeacher(t) {
  document.getElementById('teacher-modal-title').textContent = 'Edit Teacher';
  document.getElementById('edit-teacher-id').value = t.id;
  document.getElementById('t-name').value = t.name;
  document.getElementById('t-tcode').value = t.teaching_code;
  document.getElementById('t-pcode').value = '';
  document.getElementById('t-auth').checked = t.authorised;
  document.getElementById('t-active').checked = t.active;
  openModal('teacher-modal');
}

async function saveTeacher() {
  const id = document.getElementById('edit-teacher-id').value;
  const name = document.getElementById('t-name').value.trim();
  const teaching_code = document.getElementById('t-tcode').value.trim();
  const passcode = document.getElementById('t-pcode').value.trim();
  const authorised = document.getElementById('t-auth').checked;
  const active = document.getElementById('t-active').checked;
  const err = document.getElementById('teacher-modal-err');
  err.classList.add('hidden');

  if (!name || !teaching_code) {
    err.textContent = 'Name and teaching code are required.';
    err.classList.remove('hidden');
    return;
  }

  let r;
  if (id) {
    const body = { name, teaching_code, authorised, active };
    if (passcode) body.passcode = passcode;
    r = await fetch('/api/teachers/' + id, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    });
  } else {
    if (!passcode) {
      err.textContent = 'Passcode is required for new teachers.';
      err.classList.remove('hidden');
      return;
    }
    r = await fetch('/api/teachers', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, teaching_code, passcode, authorised, active })
    });
  }

  const d = await r.json();
  if (d.success || d.id) {
    closeModal('teacher-modal');
    loadTeachers();
  } else {
    err.textContent = d.error || 'Error saving.';
    err.classList.remove('hidden');
  }
}

async function deleteTeacher(id) {
  if (!confirm('Delete this teacher?')) return;
  await fetch('/api/teachers/' + id, { method: 'DELETE' });
  loadTeachers();
}

// ── ROUTES ──
async function loadRoutes() {
  const r = await fetch('/api/routes');
  const data = await r.json();
  document.getElementById('routes-body').innerHTML = data.map(rt => `
    <tr>
      <td><strong>${rt.name}</strong></td>
      <td>${rt.description || '—'}</td>
      <td>${rt.is_morning ? '🌅 Yes' : '—'}</td>
      <td>${rt.active
        ? '<span style="color:var(--success)">Active</span>'
        : '<span style="color:var(--text-light)">Inactive</span>'}</td>
      <td style="display:flex;gap:0.4rem">
        <button class="btn-sm btn-edit" onclick='editRoute(${JSON.stringify(rt)})'>Edit</button>
        <button class="btn-sm btn-del" onclick="deleteRoute(${rt.id})">Delete</button>
      </td>
    </tr>
  `).join('');
}

function editRoute(rt) {
  document.getElementById('route-modal-title').textContent = 'Edit Route';
  document.getElementById('edit-route-id').value = rt.id;
  document.getElementById('r-name').value = rt.name;
  document.getElementById('r-desc').value = rt.description || '';
  document.getElementById('r-morning').checked = rt.is_morning;
  document.getElementById('r-active').checked = rt.active;
  openModal('route-modal');
}

async function saveRoute() {
  const id = document.getElementById('edit-route-id').value;
  const name = document.getElementById('r-name').value.trim();
  const description = document.getElementById('r-desc').value.trim();
  const is_morning = document.getElementById('r-morning').checked;
  const active = document.getElementById('r-active').checked;

  if (!name) { alert('Route name required.'); return; }

  let r;
  if (id) {
    r = await fetch('/api/routes/' + id, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, description, is_morning, active })
    });
  } else {
    r = await fetch('/api/routes', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, description, is_morning })
    });
  }
  const d = await r.json();
  if (d.success || d.id) { closeModal('route-modal'); loadRoutes(); }
}

async function deleteRoute(id) {
  if (!confirm('Delete this route?')) return;
  await fetch('/api/routes/' + id, { method: 'DELETE' });
  loadRoutes();
}

// ── LOGS ──
async function loadLogs() {
  const r = await fetch('/api/logs?limit=100');
  const data = await r.json();
  document.getElementById('logs-body').innerHTML = data.map(l => `
    <tr>
      <td style="white-space:nowrap">${l.timestamp}</td>
      <td><span class="badge-role" style="background:${l.user_type === 'admin' ? 'var(--red)' : 'var(--sky)'}">${l.user_type}</span></td>
      <td>${l.user_name}</td>
      <td>${l.action}</td>
      <td style="color:var(--text-light);font-size:0.8rem">${l.ip}</td>
    </tr>
  `).join('') || '<tr><td colspan="5" class="muted" style="text-align:center;padding:1rem">No logs yet.</td></tr>';
}

// ── ADMINS ──
async function loadAdmins() {
  const r = await fetch('/api/admins');
  const data = await r.json();
  document.getElementById('admins-body').innerHTML = data.map(a => `
    <tr>
      <td><strong>${a.username}</strong></td>
      <td>${a.role}</td>
      <td>
        <button class="btn-sm btn-del" onclick="deleteAdmin(${a.id})">Delete</button>
      </td>
    </tr>
  `).join('');
}

async function saveAdmin() {
  const username = document.getElementById('adm-user').value.trim();
  const password = document.getElementById('adm-pass').value.trim();
  const role = document.getElementById('adm-role').value;
  const err = document.getElementById('admin-modal-err');
  err.classList.add('hidden');

  if (!username || !password) {
    err.textContent = 'Username and password required.';
    err.classList.remove('hidden');
    return;
  }

  const r = await fetch('/api/admins', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password, role })
  });
  const d = await r.json();
  if (d.success) {
    closeModal('admin-modal');
    loadAdmins();
  } else {
    err.textContent = d.error || 'Error.';
    err.classList.remove('hidden');
  }
}

async function deleteAdmin(id) {
  if (!confirm('Delete this admin?')) return;
  await fetch('/api/admins/' + id, { method: 'DELETE' });
  loadAdmins();
}

// ── Wire up modal open buttons ──
document.addEventListener('DOMContentLoaded', () => {
  // Patch Add Teacher button
  const addTeacherBtns = document.querySelectorAll("button[onclick=\"openModal('teacher-modal')\"]");
  addTeacherBtns.forEach(b => {
    b.setAttribute('onclick', 'openAddTeacher()');
  });
  // Patch Add Route button
  const addRouteBtns = document.querySelectorAll("button[onclick=\"openModal('route-modal')\"]");
  addRouteBtns.forEach(b => {
    b.setAttribute('onclick', 'openAddRoute()');
  });
});

function openAddRoute() {
  document.getElementById('route-modal-title').textContent = 'Add Route';
  document.getElementById('edit-route-id').value = '';
  document.getElementById('r-name').value = '';
  document.getElementById('r-desc').value = '';
  document.getElementById('r-morning').checked = false;
  document.getElementById('r-active').checked = true;
  openModal('route-modal');
}

// Init
initPage();
