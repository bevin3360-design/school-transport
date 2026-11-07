/* Shared live vehicle map for drivers, parents, teachers and school admins. */
(() => {
  'use strict';

  const STYLE_ID = 'vehicle-map-styles';
  const REFRESH_MS = 12000;
  let role = null;
  let map = null;
  let markers = new Map();
  let refreshTimer = null;
  let isOpen = false;
  let mapLibraryPromise = null;

  function addStyles() {
    if (document.getElementById(STYLE_ID)) return;
    const style = document.createElement('style');
    style.id = STYLE_ID;
    style.textContent = `
      #vehicle-map-launcher{position:fixed;right:18px;bottom:18px;z-index:3000;border:0;border-radius:999px;
        padding:13px 18px;background:#153b50;color:#fff;font:700 15px system-ui;box-shadow:0 6px 24px #102f4260;cursor:pointer}
      #vehicle-map-launcher:focus-visible,#vehicle-map-close:focus-visible,#vehicle-map-refresh:focus-visible{outline:3px solid #f4bd4f;outline-offset:3px}
      #vehicle-map-panel{position:fixed;inset:auto 16px 76px auto;z-index:2999;width:min(760px,calc(100vw - 32px));height:min(78vh,700px);
        display:none;grid-template-rows:auto auto 1fr auto;background:#fff;border-radius:18px;overflow:hidden;box-shadow:0 12px 50px #102f4260;color:#173042;font:14px system-ui}
      #vehicle-map-panel.open{display:grid}
      .vehicle-map-head{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:14px 16px;background:#153b50;color:white}
      .vehicle-map-head h2{margin:0;font-size:17px}.vehicle-map-head p{margin:4px 0 0;color:#d4e5ed;font-size:12px}
      .vehicle-map-actions{display:flex;gap:8px}.vehicle-map-actions button{border:1px solid #ffffff70;background:transparent;color:#fff;border-radius:8px;padding:8px 10px;cursor:pointer;font-weight:700}
      #vehicle-map-status{padding:10px 16px;background:#f2f7f8;color:#284656;min-height:40px}
      #vehicle-live-map{min-height:180px;width:100%;background:#e8eff0}
      #vehicle-map-list{max-height:150px;overflow:auto;padding:8px 12px;border-top:1px solid #e3eaed}
      .vehicle-row{display:flex;align-items:center;justify-content:space-between;gap:10px;padding:8px;border-bottom:1px solid #edf1f3}
      .vehicle-row:last-child{border-bottom:0}.vehicle-row strong{display:block;color:#173042}.vehicle-row small{color:#607987}
      .vehicle-live{color:#18804a;font-weight:700}.vehicle-offline{color:#8a5a00;font-weight:700}
      .vehicle-map-note{padding:8px 14px;background:#fff7df;color:#654f10;font-size:12px}
      @media(max-width:600px){#vehicle-map-panel{inset:auto 8px 8px;width:calc(100vw - 16px);height:min(88vh,760px);border-radius:16px}
        #vehicle-map-launcher{right:12px;bottom:12px}#vehicle-live-map{min-height:180px}.vehicle-map-head{padding:12px}.vehicle-map-actions button{padding:7px}}
    `;
    document.head.appendChild(style);
  }

  function makeButton(label, action, id) {
    const button = document.createElement('button');
    button.type = 'button';
    button.textContent = label;
    if (id) button.id = id;
    button.addEventListener('click', action);
    return button;
  }

  function buildWidget() {
    addStyles();
    const launcher = makeButton('📍 Live vehicle map', togglePanel, 'vehicle-map-launcher');
    launcher.setAttribute('aria-controls', 'vehicle-map-panel');
    launcher.setAttribute('aria-expanded', 'false');
    const panel = document.createElement('section');
    panel.id = 'vehicle-map-panel';
    panel.setAttribute('aria-label', 'Live vehicle locations');

    const header = document.createElement('header');
    header.className = 'vehicle-map-head';
    const titleWrap = document.createElement('div');
    const title = document.createElement('h2');
    title.textContent = 'School vehicle locations';
    const subtitle = document.createElement('p');
    subtitle.textContent = 'GPS updates refresh automatically. Location is shared only with authorised school users.';
    titleWrap.append(title, subtitle);
    const actions = document.createElement('div');
    actions.className = 'vehicle-map-actions';
    actions.append(
      makeButton('Refresh', refreshLocations, 'vehicle-map-refresh'),
      makeButton('Close', togglePanel, 'vehicle-map-close')
    );
    header.append(titleWrap, actions);

    const status = document.createElement('div');
    status.id = 'vehicle-map-status';
    status.setAttribute('role', 'status');
    status.setAttribute('aria-live', 'polite');
    status.textContent = 'Loading vehicle locations…';
    const mapEl = document.createElement('div');
    mapEl.id = 'vehicle-live-map';
    mapEl.setAttribute('aria-label', 'Map showing authorised school vehicles');
    const list = document.createElement('div');
    list.id = 'vehicle-map-list';
    const note = document.createElement('div');
    note.className = 'vehicle-map-note';
    note.textContent = 'Map pins show the last GPS position received. A stale or offline pin is not a guaranteed current position. Drivers should stop safely before using the map.';
    panel.append(header, status, mapEl, list, note);
    document.body.append(launcher, panel);
  }

  function loadLeaflet() {
    if (window.L) return Promise.resolve();
    if (mapLibraryPromise) return mapLibraryPromise;
    mapLibraryPromise = new Promise((resolve, reject) => {
      if (!document.querySelector('link[data-vehicle-leaflet]')) {
        const css = document.createElement('link');
        css.rel = 'stylesheet';
        css.href = 'https://unpkg.com/leaflet@1.9.4/dist/leaflet.css';
        css.dataset.vehicleLeaflet = 'true';
        document.head.appendChild(css);
      }
      const script = document.createElement('script');
      script.src = 'https://unpkg.com/leaflet@1.9.4/dist/leaflet.js';
      script.onload = resolve;
      script.onerror = () => reject(new Error('Map library could not be loaded. Check your internet connection.'));
      document.head.appendChild(script);
    });
    return mapLibraryPromise;
  }

  function initialiseMap() {
    if (map || !window.L) return;
    map = L.map('vehicle-live-map', {scrollWheelZoom: false}).setView([-1.2921, 36.8219], 11);
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      attribution: '© OpenStreetMap contributors', maxZoom: 19
    }).addTo(map);
  }

  function setStatus(message) {
    const status = document.getElementById('vehicle-map-status');
    if (status) status.textContent = message;
  }

  function timeLabel(value) {
    if (!value) return 'No GPS update received';
    const seconds = Math.max(0, Math.floor((Date.now() - new Date(value).getTime()) / 1000));
    if (!Number.isFinite(seconds)) return 'Update time unavailable';
    if (seconds < 60) return `Updated ${seconds}s ago`;
    return `Updated ${Math.floor(seconds / 60)}m ago`;
  }

  function makeBusIcon(live, stale) {
    const color = !live ? '#9a6a18' : (stale ? '#9a6a18' : '#16804a');
    return L.divIcon({
      className: '', iconSize: [38, 38], iconAnchor: [19, 19],
      html: `<div style="width:36px;height:36px;border-radius:50%;display:grid;place-items:center;background:${color};border:3px solid white;box-shadow:0 2px 8px #0005;font-size:19px">🚌</div>`
    });
  }

  function renderVehicles(payload) {
    initialiseMap();
    const vehicles = payload.vehicles || [];
    const list = document.getElementById('vehicle-map-list');
    list.replaceChildren();
    const active = [];
    const currentIds = new Set(vehicles.map(vehicle => String(vehicle.id)));
    markers.forEach((marker, id) => {
      if (!currentIds.has(id)) { map.removeLayer(marker); markers.delete(id); }
    });

    vehicles.forEach(vehicle => {
      const hasCoordinates = vehicle.is_tracking && Number.isFinite(Number(vehicle.latitude)) && Number.isFinite(Number(vehicle.longitude));
      const age = vehicle.last_update ? (Date.now() - new Date(vehicle.last_update).getTime()) / 1000 : Infinity;
      const stale = hasCoordinates && age > 60;
      const row = document.createElement('div');
      row.className = 'vehicle-row';
      const details = document.createElement('div');
      const driver = document.createElement('strong');
      driver.textContent = vehicle.driver_name || 'School vehicle';
      const route = document.createElement('small');
      route.textContent = `${vehicle.route_name || 'Route not assigned'}${vehicle.route_type ? ` · ${vehicle.route_type}` : ''} · ${timeLabel(vehicle.last_update)}`;
      details.append(driver, route);
      const state = document.createElement('span');
      state.className = hasCoordinates && !stale ? 'vehicle-live' : 'vehicle-offline';
      state.textContent = !hasCoordinates ? 'OFFLINE' : (stale ? 'STALE GPS' : 'LIVE');
      row.append(details, state);
      if (hasCoordinates) {
        const position = [Number(vehicle.latitude), Number(vehicle.longitude)];
        let marker = markers.get(String(vehicle.id));
        if (!marker) {
          marker = L.marker(position, {icon: makeBusIcon(true, stale)}).addTo(map);
          markers.set(String(vehicle.id), marker);
        } else {
          marker.setLatLng(position).setIcon(makeBusIcon(true, stale));
        }
        const popup = document.createElement('div');
        const name = document.createElement('strong');
        name.textContent = vehicle.driver_name || 'School vehicle';
        const detail = document.createElement('div');
        detail.textContent = `${vehicle.route_name || 'Route'} · ${timeLabel(vehicle.last_update)}${stale ? ' · GPS may be out of date' : ''}`;
        popup.append(name, detail);
        marker.bindPopup(popup);
        row.tabIndex = 0;
        row.setAttribute('role', 'button');
        row.setAttribute('aria-label', `Show ${vehicle.route_name || 'vehicle'} on map`);
        const focus = () => { map.setView(position, 16); marker.openPopup(); };
        row.addEventListener('click', focus);
        row.addEventListener('keydown', event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); focus(); } });
        active.push(position);
      }
      list.appendChild(row);
    });

    if (vehicles.length === 0) {
      const empty = document.createElement('p');
      empty.style.cssText = 'padding:8px;color:#607987;margin:0';
      empty.textContent = payload.message || 'No vehicles are assigned to a route visible to your account.';
      list.appendChild(empty);
    }
    if (active.length && !map._vehicleUserMoved) {
      if (active.length === 1) map.setView(active[0], 15);
      else map.fitBounds(active, {padding: [28, 28], maxZoom: 15});
    }
    if (!active.length) setStatus(payload.message || 'No live GPS positions yet. Offline vehicles will appear here when the driver starts GPS sharing.');
    else setStatus(`${active.length} vehicle${active.length === 1 ? '' : 's'} sharing GPS · auto-refreshes every 12 seconds.`);
  }

  async function refreshLocations() {
    if (!isOpen) return;
    setStatus('Updating vehicle locations…');
    try {
      const response = await fetch('/api/vehicle/locations', {cache: 'no-store', credentials: 'same-origin'});
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || 'Could not load vehicle locations.');
      renderVehicles(payload);
    } catch (error) {
      setStatus(error.message || 'Vehicle locations are temporarily unavailable. Check your connection.');
    }
  }

  function updateDriverTrackingButton() {
    const button = document.getElementById('vehicle-map-driver-tracking');
    if (!button) return;
    button.textContent = window.isTracking ? 'Stop sharing GPS' : 'Start sharing GPS';
    button.setAttribute('aria-pressed', String(Boolean(window.isTracking)));
  }

  async function toggleDriverTracking() {
    try {
      if (typeof window.isTracking === 'boolean' && window.isTracking && typeof window.stopTracking === 'function') {
        await window.stopTracking();
      } else if (typeof window.startTracking === 'function') {
        await window.startTracking();
      } else {
        throw new Error('GPS sharing controls are unavailable on this page.');
      }
    } catch (error) {
      setStatus(error.message || 'Unable to change GPS sharing.');
    }
    setTimeout(() => { updateDriverTrackingButton(); refreshLocations(); }, 500);
  }

  async function togglePanel() {
    isOpen = !isOpen;
    const panel = document.getElementById('vehicle-map-panel');
    const launcher = document.getElementById('vehicle-map-launcher');
    panel.classList.toggle('open', isOpen);
    launcher.setAttribute('aria-expanded', String(isOpen));
    if (!isOpen) {
      if (refreshTimer) clearInterval(refreshTimer);
      refreshTimer = null;
      launcher.focus();
      return;
    }
    try {
      await loadLeaflet();
      initialiseMap();
      if (role === 'driver' && !document.getElementById('vehicle-map-driver-tracking')) {
        const button = makeButton('', toggleDriverTracking, 'vehicle-map-driver-tracking');
        document.querySelector('.vehicle-map-actions').prepend(button);
        updateDriverTrackingButton();
        if (typeof window.isTracking === 'boolean' && window.isTracking && !window.trackingInterval && typeof window.updateLocation === 'function') {
          window.trackingInterval = setInterval(window.updateLocation, 10000);
          window.updateLocation();
          if (typeof window.updateTrackingUI === 'function') window.updateTrackingUI();
        }
      }
      setTimeout(() => map.invalidateSize(), 80);
      await refreshLocations();
      if (refreshTimer) clearInterval(refreshTimer);
      refreshTimer = setInterval(() => {
        refreshLocations();
        if (role === 'driver') updateDriverTrackingButton();
      }, REFRESH_MS);
      document.getElementById('vehicle-map-close').focus();
    } catch (error) {
      setStatus(error.message || 'Map could not be loaded.');
    }
  }

  async function init() {
    try {
      const response = await fetch('/api/session', {credentials: 'same-origin'});
      const session = await response.json();
      role = session.type;
      if (!['driver', 'parent', 'teacher', 'admin'].includes(role)) return;
      buildWidget();
    } catch (_) {
      // Do not show the map widget if authentication/session status is unavailable.
    }
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init, {once: true});
  else init();
})();
