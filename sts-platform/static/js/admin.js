const today = new Date().toISOString().split('T')[0];
document.getElementById('roster-date').value = today;

function showSection(name,el){
  document.querySelectorAll('.section').forEach(s=>s.classList.remove('active'));
  document.querySelectorAll('.nav-item').forEach(i=>i.classList.remove('active'));
  document.getElementById('section-'+name).classList.add('active');
  if(el)el.classList.add('active');
  if(name==='roster'){loadRoster();loadWeek();}
  if(name==='teachers')loadTeachers();
  if(name==='routes')loadRoutes();
  if(name==='drivers')loadDrivers();
  if(name==='parents')loadParents();
  if(name==='logs')loadLogs();
  if(name==='settings')loadSettings();
}
function openModal(id){document.getElementById(id).classList.remove('hidden');}
function closeModal(id){document.getElementById(id).classList.add('hidden');}

async function init(){
  const r=await fetch('/api/session');const d=await r.json();
  if(d.type!=='admin'){window.location.href='/';return;}
  document.getElementById('nav-user').textContent=d.school;
  document.getElementById('nav-role').textContent=d.role;
  document.getElementById('nav-school').textContent=d.school+' – Transport System';
  loadSubBanner();loadRoster();loadWeek();
}

async function loadSubBanner(){
  const r=await fetch('/api/payment/status');const d=await r.json();
  const el=document.getElementById('sub-banner');
  if(d.days_remaining<=7&&d.school_status!=='expired'){
    el.innerHTML=`<div class="sub-banner trial">⚠️ Subscription: <strong>${d.days_remaining} days remaining</strong> on <strong>${d.plan}</strong> plan.
      <a href="/payment" style="color:var(--red);font-weight:700">Renew Now →</a></div>`;}
  else if(d.school_status==='expired'){
    el.innerHTML=`<div class="sub-banner expired">🔴 Subscription EXPIRED. <a href="/payment" style="color:var(--red);font-weight:700">Renew to continue →</a></div>`;}
}

async function loadRoster(){
  const dv=document.getElementById('roster-date').value||today;
  const r=await fetch('/api/roster?date='+dv);const data=await r.json();
  const msg=document.getElementById('roster-msg');const wrap=document.getElementById('roster-table-wrap');
  msg.classList.add('hidden');wrap.style.display='block';
  const d=new Date(dv+'T12:00:00');if(d.getDay()===0||d.getDay()===6){
    msg.textContent='🎉 Weekend — No roster needed.';msg.classList.remove('hidden');wrap.style.display='none';return;}
  if(!data.length){msg.textContent='No roster for this date. Click Generate to create one.';msg.classList.remove('hidden');wrap.style.display='none';return;}
  document.getElementById('roster-body').innerHTML=data.map((a,i)=>`<tr>
    <td>${i+1}</td><td><strong>${a.teacher_name}</strong></td><td><code>${a.teaching_code}</code></td>
    <td>${a.route_name}</td><td>${a.is_morning?'🌅 Morning':'🌆 Evening'}</td>
    <td><span class="status-${a.status}">${a.status.toUpperCase()}</span></td>
    <td>${a.status!=='absent'?`<button class="btn-sm btn-warn" onclick="markAbsent(${a.id})">Absent</button>`:
      `<button class="btn-sm btn-edit" onclick="loadReplace(${a.id})">Replace</button>`}</td>
  </tr>`).join('');
}

async function generateRoster(){
  const dv=document.getElementById('roster-date').value||today;
  const r=await fetch('/api/roster/generate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({date:dv})});
  const d=await r.json();
  if(d.error)alert(d.error);else{loadRoster();loadWeek();}
}

async function loadWeek(){
  const d=new Date();const day=d.getDay();const diff=d.getDate()-day+(day===0?-6:1);
  const mon=new Date(d.setDate(diff));const start=mon.toISOString().split('T')[0];
  // Build week from Monday
  const grid=document.getElementById('week-grid');grid.innerHTML='';
  for(let i=0;i<5;i++){
    const dd=new Date(mon);dd.setDate(mon.getDate()+i);
    const ds=dd.toISOString().split('T')[0];
    const r=await fetch('/api/roster?date='+ds);const data=await r.json();
    const card=document.createElement('div');card.className='week-card';
    card.innerHTML=`<div class="week-card-header">${dd.toLocaleDateString('en',{weekday:'short',month:'short',day:'numeric'})}</div>
      <div class="week-card-body">${data.length?data.map(a=>`<div class="week-assign"><strong>${a.teacher_name}</strong><br/><small>${a.route_name}</small></div>`).join(''):
      '<p style="color:var(--muted);font-size:.82rem">No roster</p>'}</div>`;
    grid.appendChild(card);
  }
}

async function markAbsent(id){
  if(!confirm('Mark as absent?'))return;
  const r=await fetch(`/api/roster/${id}/absent`,{method:'POST'});const d=await r.json();
  loadRoster();
  if(d.suggestions&&d.suggestions.length){showReplace(id,d.suggestions);}
  else alert('Marked absent. No replacements available.');
}
async function loadReplace(id){
  const r=await fetch(`/api/roster/${id}/absent`,{method:'POST'});const d=await r.json();
  if(d.suggestions)showReplace(id,d.suggestions);
}
function showReplace(id,suggestions){
  document.getElementById('replace-aid').value=id;
  document.getElementById('replace-list').innerHTML=suggestions.map(s=>`
    <div style="display:flex;justify-content:space-between;align-items:center;padding:.7rem 1rem;background:var(--sky-light);border-radius:var(--r);border:1.5px solid var(--sky)">
      <span style="font-weight:600">${s.name} <small style="color:var(--muted)">(${s.teaching_code})</small></span>
      <button class="btn-sm btn-edit" onclick="confirmReplace(${id},${s.id})">Assign</button>
    </div>`).join('');
  openModal('replace-modal');
}
async function confirmReplace(aid,tid){
  const r=await fetch(`/api/roster/${aid}/replace`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({teacher_id:tid})});
  const d=await r.json();if(d.success){closeModal('replace-modal');loadRoster();}
}

async function loadTeachers(){
  const r=await fetch('/api/teachers');const data=await r.json();
  document.getElementById('teachers-body').innerHTML=data.map(t=>`<tr>
    <td><strong>${t.name}</strong></td><td><code>${t.teaching_code}</code></td>
    <td>${t.authorised?'<span style="color:var(--success)">✔</span>':'<span style="color:var(--red)">✘</span>'}</td>
    <td>${t.active?'<span style="color:var(--success)">Active</span>':'<span style="color:var(--muted)">Inactive</span>'}</td>
    <td style="display:flex;gap:.3rem">
      <button class="btn-sm btn-edit" onclick='editTeacher(${JSON.stringify(t)})'>Edit</button>
      <button class="btn-sm btn-del" onclick="deleteTeacher(${t.id})">Delete</button>
    </td></tr>`).join('');
}
function openAddTeacher(){
  document.getElementById('t-modal-title').textContent='Add Teacher';
  document.getElementById('t-id').value='';['t-name','t-code','t-passcode'].forEach(i=>document.getElementById(i).value='');
  document.getElementById('t-auth').checked=false;document.getElementById('t-active').checked=true;
  openModal('teacher-modal');}
function editTeacher(t){
  document.getElementById('t-modal-title').textContent='Edit Teacher';
  document.getElementById('t-id').value=t.id;document.getElementById('t-name').value=t.name;
  document.getElementById('t-code').value=t.teaching_code;document.getElementById('t-passcode').value='';
  document.getElementById('t-auth').checked=t.authorised;document.getElementById('t-active').checked=t.active;
  openModal('teacher-modal');}
async function saveTeacher(){
  const id=document.getElementById('t-id').value;
  const name=document.getElementById('t-name').value.trim();
  const teaching_code=document.getElementById('t-code').value.trim();
  const passcode=document.getElementById('t-passcode').value.trim();
  const authorised=document.getElementById('t-auth').checked;
  const active=document.getElementById('t-active').checked;
  const err=document.getElementById('t-err');err.classList.add('hidden');
  if(!name||!teaching_code){err.textContent='Name and code required.';err.classList.remove('hidden');return;}
  let r;
  if(id){const body={name,teaching_code,authorised,active};if(passcode)body.passcode=passcode;
    r=await fetch('/api/teachers/'+id,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});}
  else{if(!passcode){err.textContent='Passcode required.';err.classList.remove('hidden');return;}
    r=await fetch('/api/teachers',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name,teaching_code,passcode,authorised,active})});}
  const d=await r.json();
  if(d.success||d.id){closeModal('teacher-modal');loadTeachers();}
  else{err.textContent=d.error||'Error saving.';err.classList.remove('hidden');}
}
async function deleteTeacher(id){if(!confirm('Delete?'))return;await fetch('/api/teachers/'+id,{method:'DELETE'});loadTeachers();}

async function loadRoutes(){
  const r=await fetch('/api/routes');const data=await r.json();
  document.getElementById('routes-body').innerHTML=data.map(rt=>`<tr>
    <td><strong>${rt.name}</strong></td><td>${rt.description||'—'}</td>
    <td>${rt.is_morning?'🌅 Yes':'—'}</td>
    <td>${rt.active?'<span style="color:var(--success)">Active</span>':'<span style="color:var(--muted)">Inactive</span>'}</td>
    <td style="display:flex;gap:.3rem">
      <button class="btn-sm btn-edit" onclick='editRoute(${JSON.stringify(rt)})'>Edit</button>
      <button class="btn-sm btn-del" onclick="deleteRoute(${rt.id})">Delete</button>
    </td></tr>`).join('');
}
function openAddRoute(){
  document.getElementById('r-modal-title').textContent='Add Route';
  document.getElementById('r-id').value='';['r-name','r-desc'].forEach(i=>document.getElementById(i).value='');
  document.getElementById('r-morning').checked=false;document.getElementById('r-active').checked=true;
  openModal('route-modal');}
function editRoute(rt){
  document.getElementById('r-modal-title').textContent='Edit Route';
  document.getElementById('r-id').value=rt.id;document.getElementById('r-name').value=rt.name;
  document.getElementById('r-desc').value=rt.description||'';
  document.getElementById('r-morning').checked=rt.is_morning;document.getElementById('r-active').checked=rt.active;
  openModal('route-modal');}
async function saveRoute(){
  const id=document.getElementById('r-id').value;
  const name=document.getElementById('r-name').value.trim();
  const description=document.getElementById('r-desc').value.trim();
  const is_morning=document.getElementById('r-morning').checked;
  const active=document.getElementById('r-active').checked;
  if(!name){alert('Route name required.');return;}
  let r;
  if(id)r=await fetch('/api/routes/'+id,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({name,description,is_morning,active})});
  else r=await fetch('/api/routes',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name,description,is_morning})});
  const d=await r.json();if(d.success||d.id){closeModal('route-modal');loadRoutes();}
}
async function deleteRoute(id){if(!confirm('Delete?'))return;await fetch('/api/routes/'+id,{method:'DELETE'});loadRoutes();}

async function loadLogs(){
  const r=await fetch('/api/logs');const data=await r.json();
  document.getElementById('logs-body').innerHTML=data.map(l=>`<tr>
    <td style="font-size:.82rem;white-space:nowrap">${l.time}</td>
    <td><span class="badge-${l.user_type==='admin'?'red':'sky'}">${l.user_type}</span></td>
    <td>${l.user_name}</td><td style="font-size:.85rem">${l.action}</td>
    <td style="color:var(--muted);font-size:.8rem">${l.ip}</td></tr>`).join('');
}

async function loadSettings(){
  const r=await fetch('/api/school/settings');const d=await r.json();
  document.getElementById('s-morning').checked=d.morning_active;
  document.getElementById('s-evening').checked=d.evening_active;
  document.getElementById('s-link').value=d.public_link||'';
}
async function saveSettings(){
  const r=await fetch('/api/school/settings',{method:'PUT',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({morning_active:document.getElementById('s-morning').checked,
      evening_active:document.getElementById('s-evening').checked,
      public_link:document.getElementById('s-link').value.trim()})});
  const d=await r.json();
  if(d.success){document.getElementById('settings-msg').classList.remove('hidden');
    setTimeout(()=>document.getElementById('settings-msg').classList.add('hidden'),3000);}
}
async function logout(){await fetch('/api/logout',{method:'POST'});window.location.href='/';}
init();

// Service worker auto-update
if ('serviceWorker' in navigator) {
  navigator.serviceWorker.register('/static/sw.js').then(reg => {
    window._swReg = reg;
    reg.addEventListener('updatefound', () => {
      const nw = reg.installing;
      nw.addEventListener('statechange', () => {
        if (nw.state === 'installed' && navigator.serviceWorker.controller) {
          const b = document.createElement('div');
          b.id = 'update-bar';
          b.style.cssText = 'position:fixed;top:58px;left:0;right:0;z-index:2000;background:#1a5276;color:#fff;text-align:center;padding:.7rem;font-size:.9rem;font-weight:600';
          b.innerHTML = '🔄 New version available. <button onclick="if(window._swReg&&window._swReg.waiting)window._swReg.waiting.postMessage({type:\'SKIP_WAITING\'})" style="margin-left:1rem;background:#e8a817;color:#000;border:none;padding:.3rem .9rem;border-radius:5px;font-weight:700;cursor:pointer">Update Now</button>';
          document.body.prepend(b);
        }
      });
    });
  });
  navigator.serviceWorker.addEventListener('controllerchange', () => location.reload());
}


// ══════════════════════════════════════════════════════
// DRIVERS MANAGEMENT
// ══════════════════════════════════════════════════════
async function loadDrivers() {
  const r = await fetch('/api/admin/drivers');
  const drivers = await r.json();
  const tbody = document.getElementById('drivers-body');
  
  if (drivers.length === 0) {
    tbody.innerHTML = '<tr><td colspan="6" style="text-align:center;color:var(--muted);">No drivers added yet</td></tr>';
    return;
  }
  
  tbody.innerHTML = drivers.map(d => `
    <tr>
      <td>${d.name}</td>
      <td>${d.phone}</td>
      <td>${d.license || 'N/A'}</td>
      <td>${d.assigned_route_name || '<span style="color:var(--muted);">Unassigned</span>'}</td>
      <td>${d.is_tracking ? '<span style="color:var(--success);">● Tracking</span>' : '<span style="color:var(--muted);">○ Offline</span>'}</td>
      <td>
        <button class="btn-sm" onclick="editDriver(${d.id})">✏️</button>
        <button class="btn-sm btn-danger" onclick="deleteDriver(${d.id},'${d.name}')">🗑️</button>
      </td>
    </tr>
  `).join('');
}

function openAddDriver() {
  document.getElementById('d-modal-title').textContent = 'Add Driver';
  document.getElementById('d-id').value = '';
  document.getElementById('d-name').value = '';
  document.getElementById('d-phone').value = '';
  document.getElementById('d-license').value = '';
  document.getElementById('d-password').value = '';
  document.getElementById('d-password').placeholder = 'Create password';
  document.getElementById('d-route').value = '';
  document.getElementById('d-active').checked = true;
  document.getElementById('d-err').classList.add('hidden');
  
  // Populate route dropdown
  populateRouteDropdown('d-route');
  
  document.getElementById('driver-modal').classList.remove('hidden');
}

async function editDriver(id) {
  const r = await fetch('/api/admin/drivers');
  const drivers = await r.json();
  const driver = drivers.find(d => d.id === id);
  if (!driver) return;
  
  document.getElementById('d-modal-title').textContent = 'Edit Driver';
  document.getElementById('d-id').value = driver.id;
  document.getElementById('d-name').value = driver.name;
  document.getElementById('d-phone').value = driver.phone;
  document.getElementById('d-license').value = driver.license || '';
  document.getElementById('d-password').value = '';
  document.getElementById('d-password').placeholder = 'Leave blank to keep current';
  document.getElementById('d-route').value = driver.assigned_route_id || '';
  document.getElementById('d-active').checked = driver.active;
  document.getElementById('d-err').classList.add('hidden');
  
  populateRouteDropdown('d-route');
  
  document.getElementById('driver-modal').classList.remove('hidden');
}

async function saveDriver() {
  const id = document.getElementById('d-id').value;
  const name = document.getElementById('d-name').value.trim();
  const phone = document.getElementById('d-phone').value.trim();
  const license = document.getElementById('d-license').value.trim();
  const password = document.getElementById('d-password').value;
  const route_id = document.getElementById('d-route').value || null;
  const active = document.getElementById('d-active').checked;
  const errEl = document.getElementById('d-err');
  
  if (!name || !phone) {
    errEl.textContent = 'Name and phone are required';
    errEl.classList.remove('hidden');
    return;
  }
  
  if (!id && !password) {
    errEl.textContent = 'Password is required for new drivers';
    errEl.classList.remove('hidden');
    return;
  }
  
  const data = { name, phone, license, active, assigned_route_id: route_id };
  if (password) data.password = password;
  
  try {
    let r;
    if (id) {
      r = await fetch(`/api/admin/driver/${id}/edit`, {
        method: 'PUT',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(data)
      });
    } else {
      r = await fetch('/api/admin/driver/create', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(data)
      });
    }
    
    if (r.ok) {
      closeModal('driver-modal');
      await loadDrivers();
    } else {
      const err = await r.json();
      errEl.textContent = err.error || 'Error saving driver';
      errEl.classList.remove('hidden');
    }
  } catch (err) {
    errEl.textContent = 'Network error';
    errEl.classList.remove('hidden');
  }
}

async function deleteDriver(id, name) {
  if (!confirm(`Delete driver ${name}?\n\nThis will also delete their location history.`)) return;
  
  const r = await fetch(`/api/admin/driver/${id}/delete`, { method: 'DELETE' });
  if (r.ok) {
    await loadDrivers();
  } else {
    alert('Error deleting driver');
  }
}

// ══════════════════════════════════════════════════════
// PARENTS MANAGEMENT
// ══════════════════════════════════════════════════════
async function loadParents() {
  const r = await fetch('/api/admin/parents');
  const parents = await r.json();
  const tbody = document.getElementById('parents-body');
  
  if (parents.length === 0) {
    tbody.innerHTML = '<tr><td colspan="6" style="text-align:center;color:var(--muted);">No parents added yet</td></tr>';
    return;
  }
  
  tbody.innerHTML = parents.map(p => `
    <tr>
      <td>${p.name}</td>
      <td>${p.phone}</td>
      <td>${p.child_name || 'N/A'}</td>
      <td>${p.child_class || 'N/A'}</td>
      <td>${p.assigned_route_name || '<span style="color:var(--muted);">Unassigned</span>'}</td>
      <td>
        <button class="btn-sm" onclick="editParent(${p.id})">✏️</button>
        <button class="btn-sm btn-danger" onclick="deleteParent(${p.id},'${p.name}')">🗑️</button>
      </td>
    </tr>
  `).join('');
}

function openAddParent() {
  document.getElementById('p-modal-title').textContent = 'Add Parent';
  document.getElementById('p-id').value = '';
  document.getElementById('p-name').value = '';
  document.getElementById('p-phone').value = '';
  document.getElementById('p-password').value = '';
  document.getElementById('p-password').placeholder = 'Create password';
  document.getElementById('p-child-name').value = '';
  document.getElementById('p-child-class').value = '';
  document.getElementById('p-route').value = '';
  document.getElementById('p-active').checked = true;
  document.getElementById('p-err').classList.add('hidden');
  
  populateRouteDropdown('p-route');
  
  document.getElementById('parent-modal').classList.remove('hidden');
}

async function editParent(id) {
  const r = await fetch('/api/admin/parents');
  const parents = await r.json();
  const parent = parents.find(p => p.id === id);
  if (!parent) return;
  
  document.getElementById('p-modal-title').textContent = 'Edit Parent';
  document.getElementById('p-id').value = parent.id;
  document.getElementById('p-name').value = parent.name;
  document.getElementById('p-phone').value = parent.phone;
  document.getElementById('p-password').value = '';
  document.getElementById('p-password').placeholder = 'Leave blank to keep current';
  document.getElementById('p-child-name').value = parent.child_name || '';
  document.getElementById('p-child-class').value = parent.child_class || '';
  document.getElementById('p-route').value = parent.assigned_route_id || '';
  document.getElementById('p-active').checked = parent.active;
  document.getElementById('p-err').classList.add('hidden');
  
  populateRouteDropdown('p-route');
  
  document.getElementById('parent-modal').classList.remove('hidden');
}

async function saveParent() {
  const id = document.getElementById('p-id').value;
  const name = document.getElementById('p-name').value.trim();
  const phone = document.getElementById('p-phone').value.trim();
  const password = document.getElementById('p-password').value;
  const child_name = document.getElementById('p-child-name').value.trim();
  const child_class = document.getElementById('p-child-class').value.trim();
  const route_id = document.getElementById('p-route').value || null;
  const active = document.getElementById('p-active').checked;
  const errEl = document.getElementById('p-err');
  
  if (!name || !phone) {
    errEl.textContent = 'Name and phone are required';
    errEl.classList.remove('hidden');
    return;
  }
  
  if (!id && !password) {
    errEl.textContent = 'Password is required for new parents';
    errEl.classList.remove('hidden');
    return;
  }
  
  const data = { name, phone, child_name, child_class, active, assigned_route_id: route_id };
  if (password) data.password = password;
  
  try {
    let r;
    if (id) {
      r = await fetch(`/api/admin/parent/${id}/edit`, {
        method: 'PUT',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(data)
      });
    } else {
      r = await fetch('/api/admin/parent/create', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(data)
      });
    }
    
    if (r.ok) {
      closeModal('parent-modal');
      await loadParents();
    } else {
      const err = await r.json();
      errEl.textContent = err.error || 'Error saving parent';
      errEl.classList.remove('hidden');
    }
  } catch (err) {
    errEl.textContent = 'Network error';
    errEl.classList.remove('hidden');
  }
}

async function deleteParent(id, name) {
  if (!confirm(`Delete parent ${name}?`)) return;
  
  const r = await fetch(`/api/admin/parent/${id}/delete`, { method: 'DELETE' });
  if (r.ok) {
    await loadParents();
  } else {
    alert('Error deleting parent');
  }
}

// Helper function to populate route dropdowns
async function populateRouteDropdown(selectId) {
  const r = await fetch('/api/routes');
  const routes = await r.json();
  const select = document.getElementById(selectId);
  
  routes.forEach(route => {
    const opt = document.createElement('option');
    opt.value = route.id;
    opt.textContent = `${route.name} (${route.is_morning ? 'Morning' : 'Evening'})`;
    select.appendChild(opt);
  });
}
