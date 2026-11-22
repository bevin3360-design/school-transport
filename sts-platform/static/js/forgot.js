(function () {
  var ROLE_INFO = {
    admin:   { title: 'Forgot admin password', label: 'Admin username', placeholder: 'e.g. schooladmin', school: false },
    teacher: { title: 'Forgot teacher passcode', label: 'Teaching code', placeholder: 'e.g. TCH018', school: true },
    driver:  { title: 'Forgot driver password', label: 'Phone number', placeholder: '0712345678', school: true },
    parent:  { title: 'Forgot parent password', label: 'Phone number', placeholder: '0712345678', school: true }
  };

  function byId(id) { return document.getElementById(id); }

  function buildModal() {
    if (byId('forgot-modal')) return;
    var wrap = document.createElement('div');
    wrap.id = 'forgot-modal';
    wrap.className = 'modal-overlay hidden';
    wrap.innerHTML =
      '<div class="modal">' +
        '<div class="modal-header"><h3 id="forgot-title">Forgot password</h3>' +
          '<button class="modal-close" type="button" data-close="1">&#10005;</button></div>' +
        '<p style="color:var(--muted);font-size:.85rem;margin-bottom:1rem;">' +
          'Send a reset request to your school admin. They will set a temporary password for you.</p>' +
        '<div class="form-group" id="forgot-school-group"><label>School Code</label>' +
          '<input type="text" id="forgot-school" autocomplete="off"/></div>' +
        '<div class="form-group"><label id="forgot-id-label">Username</label>' +
          '<input type="text" id="forgot-id" autocomplete="off"/></div>' +
        '<p id="forgot-msg" class="error-msg hidden"></p>' +
        '<div class="modal-footer">' +
          '<button class="btn-outline" type="button" data-close="1">Cancel</button>' +
          '<button class="btn-primary" type="button" id="forgot-send">Send Request</button></div>' +
      '</div>';
    document.body.appendChild(wrap);
    wrap.addEventListener('click', function (e) {
      if (e.target === wrap || e.target.getAttribute('data-close')) {
        wrap.classList.add('hidden');
      }
    });
    byId('forgot-send').addEventListener('click', submit);
    byId('forgot-id').addEventListener('keydown', function (e) {
      if (e.key === 'Enter') submit();
    });
  }

  function setMsg(text, ok) {
    var msg = byId('forgot-msg');
    msg.textContent = text || '';
    msg.className = (ok ? 'success-msg' : 'error-msg') + (text ? '' : ' hidden');
  }

  async function submit() {
    var role = byId('forgot-modal').getAttribute('data-role');
    var school = byId('forgot-school').value.trim();
    var id = byId('forgot-id').value.trim();
    var info = ROLE_INFO[role] || {};
    if (info.school && !school) return setMsg('Enter your school code.', false);
    if (!id) return setMsg('Enter your ' + (info.label || 'details').toLowerCase() + '.', false);
    var btn = byId('forgot-send');
    btn.disabled = true;
    try {
      var res = await fetch('/api/account/forgot-password', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ role: role, school_code: school, identifier: id })
      });
      var data = {};
      try { data = await res.json(); } catch (e) {}
      if (data.success) {
        setMsg(data.message || 'Request sent.', true);
        byId('forgot-send').style.display = 'none';
      } else {
        setMsg(data.message || 'Could not send the request.', false);
      }
    } catch (e) {
      setMsg('Network error. Try again.', false);
    } finally {
      btn.disabled = false;
    }
  }

  window.openForgot = function (role) {
    var info = ROLE_INFO[role];
    if (!info) return;
    buildModal();
    var wrap = byId('forgot-modal');
    wrap.setAttribute('data-role', role);
    byId('forgot-title').textContent = info.title;
    byId('forgot-id-label').textContent = info.label;
    byId('forgot-id').value = '';
    byId('forgot-id').placeholder = info.placeholder;
    byId('forgot-school').value = '';
    byId('forgot-school-group').classList.toggle('hidden', !info.school);
    byId('forgot-send').style.display = '';
    setMsg('');
    wrap.classList.remove('hidden');
    (info.school ? byId('forgot-school') : byId('forgot-id')).focus();
  };
})();
