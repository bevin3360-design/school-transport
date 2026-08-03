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
