(function () {
  var ROLE_LABELS = {
    admin: 'School admin', teacher: 'Teacher',
    driver: 'Driver', parent: 'Parent'
  };

  function byId(id) { return document.getElementById(id); }

  function esc(value) {
    var d = document.createElement('div');
    d.textContent = value == null ? '' : String(value);
    return d.innerHTML;
  }

  function setMsg(node, text, ok) {
    node.textContent = text || '';
    node.className = (ok ? 'success-msg' : 'error-msg') + (text ? '' : ' hidden');
  }

  function open(wrap) { wrap.classList.remove('hidden'); }
  function close(wrap) { wrap.classList.add('hidden'); }

  async function postJson(url, body) {
    var res = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body || {})
    });
    var data = {};
    try { data = await res.json(); } catch (e) {}
    return { ok: res.ok, data: data };
  }

  function buildPasswordModal() {
    if (byId('acct-pw-modal')) return;
    var wrap = document.createElement('div');
    wrap.id = 'acct-pw-modal';
    wrap.className = 'modal-overlay hidden';
    wrap.innerHTML =
      '<div class="modal">' +
        '<div class="modal-header"><h3>Change Password</h3>' +
          '<button class="modal-close" type="button" data-close="1">&#10005;</button></div>' +
        '<div class="form-group"><label>Current password</label>' +
          '<input type="password" id="acct-pw-current" autocomplete="current-password"/></div>' +
        '<div class="form-group"><label>New password</label>' +
          '<input type="password" id="acct-pw-new" autocomplete="new-password" placeholder="At least 8 characters with a letter and a number"/></div>' +
        '<div class="form-group"><label>Confirm new password</label>' +
          '<input type="password" id="acct-pw-confirm" autocomplete="new-password"/></div>' +
        '<p id="acct-pw-msg" class="error-msg hidden"></p>' +
        '<div class="modal-footer">' +
          '<button class="btn-outline" type="button" data-close="1">Cancel</button>' +
          '<button class="btn-primary" type="button" id="acct-pw-save">Save</button></div>' +
      '</div>';
    document.body.appendChild(wrap);
    wrap.addEventListener('click', function (e) {
      if (e.target === wrap || e.target.getAttribute('data-close')) close(wrap);
    });
    byId('acct-pw-save').addEventListener('click', savePassword);
    ['acct-pw-current', 'acct-pw-new', 'acct-pw-confirm'].forEach(function (id) {
      byId(id).addEventListener('keydown', function (e) {
        if (e.key === 'Enter') savePassword();
      });
    });
  }

  async function savePassword() {
    var msg = byId('acct-pw-msg');
    var current = byId('acct-pw-current').value;
    var next = byId('acct-pw-new').value;
    var confirm = byId('acct-pw-confirm').value;
    if (!current) return setMsg(msg, 'Enter your current password.', false);
    if (next.length < 8) return setMsg(msg, 'New password must be at least 8 characters.', false);
    if (next !== confirm) return setMsg(msg, 'New passwords do not match.', false);
    var btn = byId('acct-pw-save');
    btn.disabled = true;
    try {
      var r = await postJson('/api/account/change-password', {
        current_password: current, new_password: next
      });
      if (r.data.success) {
        setMsg(msg, r.data.message || 'Password updated.', true);
        byId('acct-pw-current').value = '';
        byId('acct-pw-new').value = '';
        byId('acct-pw-confirm').value = '';
      } else {
        setMsg(msg, r.data.message || 'Could not update the password.', false);
      }
    } catch (e) {
      setMsg(msg, 'Network error. Try again.', false);
    } finally {
      btn.disabled = false;
    }
  }

  function openPasswordModal() {
    buildPasswordModal();
    setMsg(byId('acct-pw-msg'), '');
    open(byId('acct-pw-modal'));
    byId('acct-pw-current').focus();
  }

  function buildRequestsModal() {
    if (byId('acct-rq-modal')) return;
    var wrap = document.createElement('div');
    wrap.id = 'acct-rq-modal';
    wrap.className = 'modal-overlay hidden';
    wrap.innerHTML =
      '<div class="modal">' +
        '<div class="modal-header"><h3>Password Reset Requests</h3>' +
          '<button class="modal-close" type="button" data-close="1">&#10005;</button></div>' +
        '<p style="color:var(--muted);font-size:.85rem;margin-bottom:1rem;">' +
          'People who forgot their password. Set a temporary password, then tell them to change it after signing in.</p>' +
        '<div id="acct-rq-list" style="max-height:55vh;overflow-y:auto;"></div>' +
        '<div class="modal-footer"><button class="btn-outline" type="button" data-close="1">Close</button></div>' +
      '</div>';
    document.body.appendChild(wrap);
    wrap.addEventListener('click', function (e) {
      if (e.target === wrap || e.target.getAttribute('data-close')) close(wrap);
    });
  }

  function requestItem(item) {
    var card = document.createElement('div');
    card.style.cssText = 'border:1px solid var(--grey);border-radius:10px;padding:.9rem;margin-bottom:.8rem;';
    card.innerHTML =
      '<div style="font-size:.85rem;line-height:1.6;margin-bottom:.5rem;">' +
        '<strong>' + esc(ROLE_LABELS[item.role] || item.role) + '</strong> &middot; ' +
        esc(item.identifier) +
        (item.school ? '<br/><span style="color:var(--muted)">' + esc(item.school) + '</span>' : '') +
        '<br/><span style="color:var(--muted);font-size:.75rem;">Requested ' + esc(item.created_at) + '</span>' +
      '</div>' +
      '<input type="password" placeholder="Temporary password" style="width:100%;margin-bottom:.4rem;" />' +
      '<p class="error-msg hidden"></p>' +
      '<div style="display:flex;gap:.5rem;">' +
        '<button class="btn-primary" type="button" style="flex:1;">Reset</button>' +
        '<button class="btn-outline" type="button" style="flex:1;">Dismiss</button>' +
      '</div>';
    var input = card.querySelector('input');
    var msg = card.querySelector('.error-msg');
    var buttons = card.querySelectorAll('button');
    buttons[0].addEventListener('click', async function () {
      var value = input.value;
      if (value.length < 8) return setMsg(msg, 'Use at least 8 characters.', false);
      buttons[0].disabled = true;
      try {
        var r = await postJson('/api/' + state.type + '/password-requests/' + item.id + '/reset', {
          new_password: value
        });
        if (r.data.success) card.remove();
        else setMsg(msg, r.data.message || 'Reset failed.', false);
      } catch (e) {
        setMsg(msg, 'Network error. Try again.', false);
      } finally {
        buttons[0].disabled = false;
      }
    });
    buttons[1].addEventListener('click', async function () {
      buttons[1].disabled = true;
      try {
        var r = await postJson('/api/' + state.type + '/password-requests/' + item.id + '/reject', {});
        if (r.data.success) card.remove();
        else setMsg(msg, r.data.message || 'Could not dismiss.', false);
      } catch (e) {
        setMsg(msg, 'Network error. Try again.', false);
      } finally {
        buttons[1].disabled = false;
      }
    });
    return card;
  }

  async function openRequestsModal() {
    buildRequestsModal();
    var list = byId('acct-rq-list');
    list.innerHTML = '<p style="color:var(--muted);font-size:.9rem;">Loading…</p>';
    open(byId('acct-rq-modal'));
    try {
      var res = await fetch('/api/' + state.type + '/password-requests');
      var data = await res.json();
      list.innerHTML = '';
      if (!data.success) {
        list.innerHTML = '<p class="error-msg">' + esc(data.message || 'Could not load requests.') + '</p>';
        return;
      }
      if (!data.requests.length) {
        list.innerHTML = '<p style="color:var(--muted);font-size:.9rem;">No pending reset requests.</p>';
        return;
      }
      data.requests.forEach(function (item) { list.appendChild(requestItem(item)); });
    } catch (e) {
      list.innerHTML = '<p class="error-msg">Network error. Try again.</p>';
    }
  }

  var state = { type: null };

  function navButton(label, cls, onClick) {
    var btn = document.createElement('button');
    btn.type = 'button';
    btn.className = cls;
    btn.textContent = label;
    btn.addEventListener('click', onClick);
    return btn;
  }

  async function init() {
    var nav = document.querySelector('.nav-right');
    if (!nav) return;
    var info = null;
    try {
      var res = await fetch('/api/session');
      info = await res.json();
    } catch (e) { return; }
    if (!info || !info.type) return;
    state.type = info.type;
    var logoutBtn = nav.querySelector('button');
    var cls = logoutBtn ? logoutBtn.className : 'btn-outline-sm';
    if (info.type === 'admin' || info.type === 'super') {
      nav.insertBefore(navButton('Reset Requests', cls, openRequestsModal), logoutBtn || null);
    }
    nav.insertBefore(navButton('Password', cls, openPasswordModal), logoutBtn || null);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
