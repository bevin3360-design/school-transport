(function () {
  var meta = document.querySelector('meta[name="csrf-token"]');
  var token = meta ? meta.getAttribute('content') : '';
  if (!token || typeof window.fetch !== 'function') return;

  var originalFetch = window.fetch;
  var safeMethods = ['GET', 'HEAD', 'OPTIONS', 'TRACE'];

  window.fetch = function (input, init) {
    init = init || {};
    var method = String(
      init.method || (input && typeof input === 'object' && input.method) || 'GET'
    ).toUpperCase();
    if (safeMethods.indexOf(method) === -1) {
      var headers = new Headers(init.headers || (input && typeof input === 'object' ? input.headers : undefined));
      if (!headers.has('X-CSRFToken')) headers.set('X-CSRFToken', token);
      init.headers = headers;
    }
    return originalFetch.call(this, input, init);
  };
})();
