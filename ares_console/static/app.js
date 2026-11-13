/* ARES Console front-end (vanilla JS) */
'use strict';
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const S = { settings: {}, net: null, checkins: [], formdefs: null, box: 'inbox', map: null, layers: {}, dropMode: false, currentMsg: null };

async function api(path, opts = {}) {
  const o = { method: opts.method || 'GET', headers: {} };
  if (opts.body !== undefined) { o.body = JSON.stringify(opts.body); o.headers['Content-Type'] = 'application/json'; }
  const r = await fetch(path, o);
  const j = await r.json().catch(() => ({}));
  if (!r.ok) { const msg = j.error || r.statusText; toast(msg, true); throw new Error(msg); }
  return j;
}
const post = (p, b) => api(p, { method: 'POST', body: b || {} });
const put = (p, b) => api(p, { method: 'PUT', body: b || {} });
const del = (p) => api(p, { method: 'DELETE' });

function toast(msg, err) {
  let t = $('#toast');
  if (!t) { t = document.createElement('div'); t.id = 'toast'; document.body.appendChild(t);
    Object.assign(t.style, { position: 'fixed', bottom: '16px', left: '50%', transform: 'translateX(-50%)', padding: '8px 16px', borderRadius: '6px', color: '#fff', zIndex: 3000, maxWidth: '90vw' }); }
  t.textContent = msg; t.style.background = err ? '#b03a2e' : '#1e8449'; t.style.display = 'block';
  clearTimeout(t._h); t._h = setTimeout(() => t.style.display = 'none', err ? 6000 : 2500);
}
const fmtT = (iso) => iso ? iso.slice(11, 16) + 'Z' : '';
const fmtDT = (iso) => iso ? iso.slice(0, 10) + ' ' + iso.slice(11, 16) + 'Z' : '';
const ago = (iso) => { if (!iso) return Infinity; return (Date.now() - Date.parse(iso)) / 60000; };
const baseCall = (c) => (c || '').toUpperCase().split('-')[0];
const statuses = () => (S.settings.statuses || 'Present,Away,Checked Out').split(',').map(s => s.trim()).filter(Boolean);
const stClass = (s) => s === 'Present' ? 'st-present' : (s === 'Checked Out' ? 'st-out' : 'st-away');
const stColor = (s) => s === 'Present' ? '#1e8449' : (s === 'Checked Out' ? '#7f8c8d' : '#b9770e');

/* ---------------------------------------------------------------- modal */
function modal(title, html, onReady) {
  $('#modalTitle').textContent = title; $('#modalBody').innerHTML = html; $('#modal').classList.remove('hidden');
  if (onReady) onReady($('#modalBody'));
}
function closeModal() { $('#modal').classList.add('hidden'); $('#modalBody').innerHTML = ''; }
$('#modalClose').onclick = closeModal;
$('#modal').addEventListener('mousedown', e => { if (e.target.id === 'modal') closeModal(); });

/* ---------------------------------------------------------------- tabs */
$$('#tabs button').forEach(b => b.onclick = () => showTab(b.dataset.tab));
function showTab(t) {
  $$('#tabs button').forEach(b => b.classList.toggle('active', b.dataset.tab === t));
  $$('.tab').forEach(s => s.classList.toggle('active', s.id === 'tab-' + t));
  try { localStorage.setItem('ares.tab', t); } catch (e) { }
  if (t === 'map') { initMap(); setTimeout(() => S.map.invalidateSize(), 50); loadMap(); }
  if (t === 'forms') loadForms();
  if (t === 'winlink') { loadBox(); loadWlStatus(); loadNodes(); }
  if (t === 'js8') loadJs8();
  if (t === 'reports') loadNets();
  if (t === 'settings') fillSettings();
}

/* ---------------------------------------------------------------- clock + header */
setInterval(() => { const d = new Date(); $('#clock').textContent = d.toISOString().slice(11, 19) + 'Z  ' + d.toTimeString().slice(0, 5) + 'L'; }, 1000);

function renderHeader() {
  const s = S.settings;
  $('#orgTitle').textContent = s.org_title || 'ARES Console';
  $('#orgSub').textContent = s.org_subtitle || '';
  document.title = (s.org_title || 'ARES Console') + (S.net ? ' - NET ACTIVE' : '');
  const n = S.net;
  $('#netInfo').innerHTML = n ? `<span class="live">NET ACTIVE</span><b>${esc(n.name)}</b> · NCS ${esc(n.ncs || '')} · ${esc(n.frequency || '')} · opened ${fmtDT(n.opened_at)}` : '<span style="opacity:.7">No net open</span>';
  $('#netClosed').classList.toggle('hidden', !!n);
  $('#netOpen').classList.toggle('hidden', !n);
  if (!n) { $('#openNcs').value = $('#openNcs').value || [s.mycall, s.operator_name].filter(Boolean).join(' '); }
}
function setChip(id, status) {
  const el = $(id); el.classList.remove('ok', 'warn', 'err');
  el.title = status;
  if (/^connected/.test(status)) el.classList.add('ok');
  else if (/error|closed/.test(status)) el.classList.add('err');
  else if (/connecting|calling|exchang|transfer|await|opening/.test(status)) el.classList.add('warn');
}

/* ---------------------------------------------------------------- state */
async function loadState() {
  const st = await api('/api/state');
  S.settings = st.settings; S.net = st.net; S.checkins = st.checkins;
  setChip('#chipAPRS', st.aprs.status); setChip('#chipJS8', st.js8.status); setChip('#chipWL', st.winlink.state);
  renderHeader(); renderRoster(); loadActivity();
  const sel = $('#addStatus'); sel.innerHTML = statuses().map(s => `<option>${esc(s)}</option>`).join('');
}

/* ---------------------------------------------------------------- net open/close */
$('#btnOpenNet').onclick = async () => {
  await post('/api/net/open', { name: $('#openName').value || 'ARES Net', ncs: $('#openNcs').value, frequency: $('#openFreq').value, carry_over: $('#openCarry').checked });
  toast('Net opened'); loadState();
};
$('#btnCloseNet').onclick = () => {
  modal('Close Net', `<p>Close <b>${esc(S.net.name)}</b>? All stations still checked in will be marked Checked Out.</p>
    <label class="inline"><input type="checkbox" id="closeOut" checked> Check out remaining stations</label>
    <label class="inline"><input type="checkbox" id="closeRpt" checked> Open the summary report</label>
    <div class="row"><button class="danger" id="closeGo">Close Net</button><button id="closeCancel">Cancel</button></div>`, (b) => {
    $('#closeCancel', b).onclick = closeModal;
    $('#closeGo', b).onclick = async () => {
      const r = await post('/api/net/close', { checkout_all: $('#closeOut', b).checked });
      const rpt = $('#closeRpt', b).checked; closeModal(); toast('Net closed'); await loadState();
      if (rpt) window.open('/api/report/' + r.net_id, '_blank');
    };
  });
};
$('#btnEditNet').onclick = () => {
  const n = S.net;
  modal('Net details', `<label>Name<input id="enName" value="${esc(n.name)}"></label><label>NCS<input id="enNcs" value="${esc(n.ncs)}"></label>
   <label>Frequency<input id="enFreq" value="${esc(n.frequency)}"></label><label>Notes<textarea id="enNotes" rows="3">${esc(n.notes)}</textarea></label>
   <button class="primary" id="enSave">Save</button>`, b => {
    $('#enSave', b).onclick = async () => { await put('/api/net/' + n.id, { name: $('#enName', b).value, ncs: $('#enNcs', b).value, frequency: $('#enFreq', b).value, notes: $('#enNotes', b).value }); closeModal(); loadState(); };
  });
};

/* ---------------------------------------------------------------- roster */
$('#addForm').onsubmit = async (e) => {
  e.preventDefault();
  await post('/api/checkins', { callsign: $('#addCall').value, name: $('#addName').value, tactical: $('#addTac').value, location: $('#addLoc').value, notes: $('#addNotes').value, status: $('#addStatus').value });
  ['#addCall', '#addName', '#addTac', '#addLoc', '#addNotes'].forEach(s => $(s).value = '');
  $('#addStatus').selectedIndex = 0; $('#addCall').focus();
};
$('#rosterFilter').oninput = renderRoster;
$('#hideOut').onchange = renderRoster;
let stationsCache = [];
function posFor(call) {
  const b = baseCall(call); let best = null;
  for (const s of stationsCache) if (baseCall(s.callsign) === b && (!best || s.ts > best.ts)) best = s;
  return best;
}
function renderRoster() {
  const tb = $('#roster tbody'); if (!tb) return;
  const f = $('#rosterFilter').value.toLowerCase(); const hide = $('#hideOut').checked;
  const counts = {};
  S.checkins.forEach(c => counts[c.status] = (counts[c.status] || 0) + 1);
  $('#counts').innerHTML = `<b>${S.checkins.length}</b> stations · ` + statuses().map(s => `<span style="color:${stColor(s)}"><b>${counts[s] || 0}</b> ${esc(s)}</span>`).join(' · ');
  const active = document.activeElement; const keep = active && active.dataset && active.dataset.cid ? [active.dataset.cid, active.dataset.f] : null;
  tb.innerHTML = S.checkins.filter(c => (!hide || c.status !== 'Checked Out') && (!f || JSON.stringify(c).toLowerCase().includes(f))).map((c, i) => {
    const p = posFor(c.callsign); const a = p ? ago(p.ts) : Infinity;
    const dot = p ? `<span class="dot ${a < 30 ? 'fresh' : 'stale'}" title="${esc(p.source)} ${fmtDT(p.ts)}"></span>` : '<span class="dot" title="No position"></span>';
    return `<tr class="${c.status === 'Checked Out' ? 'is-out' : ''}">
    <td>${S.checkins.indexOf(c) + 1}</td>
    <td class="call"><input data-cid="${c.id}" data-f="callsign" value="${esc(c.callsign)}" style="font-weight:700;text-transform:uppercase"></td>
    <td><input data-cid="${c.id}" data-f="name" value="${esc(c.name)}"></td>
    <td><input data-cid="${c.id}" data-f="tactical" value="${esc(c.tactical)}"></td>
    <td><select class="st ${stClass(c.status)}" data-cid="${c.id}" data-f="status">${statuses().map(s => `<option ${s === c.status ? 'selected' : ''}>${esc(s)}</option>`).join('')}</select></td>
    <td><input data-cid="${c.id}" data-f="location" value="${esc(c.location)}"></td>
    <td><input data-cid="${c.id}" data-f="notes" value="${esc(c.notes)}"></td>
    <td title="${esc(c.time_in)}">${fmtT(c.time_in)}</td>
    <td><input type="checkbox" data-cid="${c.id}" data-f="track" ${c.track ? 'checked' : ''}></td>
    <td>${dot}${p ? ` <button class="small" data-locate="${esc(p.callsign)}">Map</button>` : ''}</td>
    <td><button class="small" data-delc="${c.id}" title="Remove from roster">✕</button></td></tr>`;
  }).join('');
  if (keep) { const el = tb.querySelector(`[data-cid="${keep[0]}"][data-f="${keep[1]}"]`); if (el) el.focus(); }
}
$('#roster').addEventListener('change', async (e) => {
  const el = e.target; if (!el.dataset.cid) return;
  const v = el.type === 'checkbox' ? el.checked : el.value;
  await put('/api/checkins/' + el.dataset.cid, { [el.dataset.f]: v });
});
$('#roster').addEventListener('keydown', e => { if (e.key === 'Enter' && e.target.tagName === 'INPUT') e.target.blur(); });
$('#roster').addEventListener('click', async (e) => {
  const d = e.target.dataset;
  if (d.delc && confirm('Remove this station from the roster? (Use status "Checked Out" to keep it in the log.)')) await del('/api/checkins/' + d.delc);
  if (d.locate) { showTab('map'); setTimeout(() => locate(d.locate), 200); }
});

/* ---------------------------------------------------------------- activity */
async function loadActivity() {
  if (!S.net) { $('#activity').innerHTML = ''; return; }
  const rows = await api('/api/activity');
  $('#activity').innerHTML = rows.map(r => `<div class="e"><span class="t">${fmtT(r.ts)}</span><span class="k">${esc(r.kind)}</span>${esc(r.text)}</div>`).join('');
}
$('#logForm').onsubmit = async (e) => {
  e.preventDefault();
  await post('/api/activity', { text: $('#logText').value, callsign: $('#logCall').value, kind: 'note' });
  $('#logText').value = ''; $('#logCall').value = '';
};

/* ---------------------------------------------------------------- map */
const MARKER_KINDS = { eoc: ['EOC', '#c0392b'], shelter: ['Shelter', '#2471a3'], hospital: ['Hospital', '#8e44ad'], staging: ['Staging', '#d35400'], spot: ['Spot', '#117a65'], hazard: ['Hazard', '#e74c3c'], net: ['Net Control', '#1b2631'], other: ['Other', '#566573'] };
function initMap() {
  if (S.map) return;
  const s = S.settings;
  S.map = L.map('map').setView([parseFloat(s.home_lat) || 39, parseFloat(s.home_lon) || -98], 9);
  setBaseLayer();
  S.map.on('moveend zoomend', () => later('seedEst', seedEstimate, 300));
  initOfflinePanel();
  S.layers.st = L.layerGroup().addTo(S.map); S.layers.tr = L.layerGroup().addTo(S.map); S.layers.mk = L.layerGroup().addTo(S.map);
  S.map.on('click', (e) => { if (S.dropMode) { setDrop(false); markerDialog({ lat: e.latlng.lat, lon: e.latlng.lng }); } });
}
/* Tile layer that, when a tile is missing (offline and never cached), shows the
   matching piece of the nearest cached lower-zoom tile, enlarged. */
async function setBaseLayer() {
  const st = await api('/api/tiles'); const p = st.preset;
  if (S.base) S.map.removeLayer(S.base);
  // Online-only sources (OpenStreetMap) load straight from their server in the browser;
  // local cache / .mbtiles packs are still tried first and used as the offline fallback.
  S.base = new OfflineTiles('/tiles/{z}/{x}/{y}.png', { maxZoom: 19, maxNativeZoom: p.max_native, direct: p.offline ? null : p.url,
    attribution: (p.attribution || '') + (p.offline ? ' · saved for offline use' : ' · online only') }).addTo(S.map);
  S.base.bringToBack();
  loadTileStatus();
}
const OfflineTiles = L.TileLayer.extend({
  createTile(coords, done) {
    const size = this.getTileSize();
    const wrap = document.createElement('div');
    wrap.style.overflow = 'hidden'; wrap.style.width = size.x + 'px'; wrap.style.height = size.y + 'px';
    const direct = this.options.direct;
    let triedDirect = false;
    const tryLevel = (k) => {
      const z = coords.z - k;
      if (z < 0 || k > 8) { done(null, wrap); return; }
      if (k === 1 && direct && !triedDirect) {  // local cache missed: try the live server once
        triedDirect = true;
        const img = document.createElement('img'); img.alt = '';
        Object.assign(img.style, { width: size.x + 'px', height: size.y + 'px' });
        img.onload = () => { wrap.appendChild(img); done(null, wrap); };
        img.onerror = () => tryLevel(1);
        img.src = direct.replace('{z}', coords.z).replace('{x}', coords.x).replace('{y}', coords.y).replace('{s}', 'abc'[(coords.x + coords.y) % 3]);
        return;
      }
      const img = document.createElement('img');
      img.alt = ''; img.setAttribute('role', 'presentation');
      const scale = 2 ** k;
      Object.assign(img.style, { position: 'absolute', width: size.x * scale + 'px', height: size.y * scale + 'px', left: -(coords.x % scale) * size.x + 'px', top: -(coords.y % scale) * size.y + 'px', maxWidth: 'none' });
      img.onload = () => { wrap.appendChild(img); done(null, wrap); };
      img.onerror = () => tryLevel(k + 1);
      img.src = `/tiles/${z}/${coords.x >> k}/${coords.y >> k}.png`;
    };
    tryLevel(0);  // (Leaflet positions the wrapper absolutely; that also anchors the child img)
    return wrap;
  }
});

const fmtBytes = n => n > 1048576 ? (n / 1048576).toFixed(1) + ' MB' : (n / 1024).toFixed(0) + ' KB';
function initOfflinePanel() {
  const opts = (sel) => { for (let z = 5; z <= 17; z++) sel.insertAdjacentHTML('beforeend', `<option>${z}</option>`); };
  opts($('#seedZmin')); opts($('#seedZmax'));
  $('#seedZmin').value = Math.max(5, Math.min(17, S.map.getZoom()));
  $('#seedZmax').value = Math.min(16, Math.max(+$('#seedZmin').value, 15));
  $('#seedZmin').onchange = seedEstimate; $('#seedZmax').onchange = seedEstimate;
  $('#btnSeed').onclick = async () => {
    const b = S.map.getBounds();
    const r = await post('/api/tiles/seed', { south: b.getSouth(), west: b.getWest(), north: b.getNorth(), east: b.getEast(), zmin: +$('#seedZmin').value, zmax: +$('#seedZmax').value });
    toast(`Saving ${r.tiles} tiles for offline use…`); showSeed({ running: true, done: 0, total: r.tiles, failed: 0, msg: 'starting' });
  };
  $('#btnSeedCancel').onclick = () => post('/api/tiles/cancel');
  $('#btnTileRetry').onclick = async () => { await post('/api/tiles/retry'); loadTileStatus(); S.map.eachLayer(l => l.redraw && l.redraw()); };
  $('#btnTileClear').onclick = async () => { if (confirm('Delete all cached map tiles? The map will not work offline until tiles are cached again.')) { await del('/api/tiles'); loadTileStatus(); } };
  loadTileStatus(); seedEstimate();
}
async function seedEstimate() {
  if (!S.map || !$('#seedZmin').value) return;
  const b = S.map.getBounds();
  const zmin = +$('#seedZmin').value, zmax = Math.max(zmin, +$('#seedZmax').value);
  const r = await api('/api/tiles/estimate', { method: 'POST', body: { south: b.getSouth(), west: b.getWest(), north: b.getNorth(), east: b.getEast(), zmin, zmax } });
  $('#seedEst').textContent = `Visible area, zoom ${zmin}–${zmax}: ${r.tiles.toLocaleString()} tiles (≈${fmtBytes(r.tiles * 25000)})` + (r.tiles > 20000 ? ' — too many, zoom in or lower “To zoom”' : '');
  $('#btnSeed').disabled = r.tiles > 20000 || S.tileOffline === false;
}
async function loadTileStatus() {
  const s = await api('/api/tiles');
  S.tileOffline = s.preset.offline;
  $('#btnSeed').title = s.preset.offline ? '' : 'This map source does not allow offline downloads';
  $('#tileStats').innerHTML = `Source: <b>${esc(s.preset.name)}</b>` + (s.preset.offline ? '' : '<br><b style="color:#b03a2e">OpenStreetMap does not allow offline saving. Pick a USGS map in Settings to save areas for offline use.</b>') + `<br>${s.cached_tiles.toLocaleString()} tiles saved (${fmtBytes(s.cached_bytes)})` + (s.mbtiles.length ? `<br>Offline packs: ${s.mbtiles.map(m => esc(m.name)).join(', ')}` : '') + `<br>Tiles folder: <code>${esc(s.tiles_dir)}</code>`;
  setTileNet(s.online);
  if (s.seed.running || s.seed.msg) showSeed(s.seed);
}
function setTileNet(online) { const c = $('#tileNet'); if (!c) return; c.textContent = online ? 'online' : 'OFFLINE'; c.className = 'chip ' + (online ? 'ok' : 'err'); }
function showSeed(sd) {
  $('#seedProg').classList.toggle('hidden', !sd.running);
  $('#btnSeedCancel').classList.toggle('hidden', !sd.running);
  $('#btnSeed').classList.toggle('hidden', !!sd.running);
  $('#seedProg').max = sd.total || 1; $('#seedProg').value = sd.done || 0;
  $('#seedMsg').textContent = sd.total ? `${sd.running ? 'Saving' : 'Finished'}: ${sd.done}/${sd.total} tiles` + (sd.skipped ? `, ${sd.skipped} already saved` : '') + (sd.failed ? `, ${sd.failed} failed` : '') + (sd.msg && !sd.running ? ` (${sd.msg})` : '') : '';
  if (!sd.running && sd.total) later('tilestat', loadTileStatus, 500);
}

function setDrop(on) {
  S.dropMode = on; $('#dropHint').textContent = on ? 'Click on the map to place the location…' : '';
  $('#map').style.cursor = on ? 'crosshair' : '';
}
$('#btnDrop').onclick = () => setDrop(!S.dropMode);
$('#showTracks').onchange = loadMap; $('#showAllStations').onchange = loadMap;
$('#btnFit').onclick = () => { const b = []; S.mapData.stations.forEach(s => b.push([s.lat, s.lon])); S.mapData.markers.forEach(m => b.push([m.lat, m.lon])); if (b.length) S.map.fitBounds(b, { padding: [40, 40], maxZoom: 14 }); };
function markerDialog(m) {
  const kinds = Object.entries(MARKER_KINDS).map(([k, v]) => `<option value="${k}" ${m.kind === k ? 'selected' : ''}>${v[0]}</option>`).join('');
  modal(m.id ? 'Edit location' : 'New map location', `<div class="grid2"><label>Label<input id="mkLabel" value="${esc(m.label || '')}" placeholder="EOC, Spot 1…"></label>
    <label>Type<select id="mkKind">${kinds}</select></label><label>Latitude<input id="mkLat" value="${m.lat.toFixed(6)}"></label><label>Longitude<input id="mkLon" value="${m.lon.toFixed(6)}"></label></div>
    <label>Notes<textarea id="mkNotes" rows="2">${esc(m.notes || '')}</textarea></label>
    ${m.id ? '' : '<label class="inline"><input type="checkbox" id="mkPerm"> Keep for all nets (permanent)</label>'}
    <div class="row"><button class="primary" id="mkSave">Save</button>${m.id ? '<button class="danger" id="mkDel">Delete</button>' : ''}</div>`, b => {
    const lab = $('#mkLabel', b); lab.focus();
    $('#mkKind', b).onchange = () => { if (!lab.value) lab.value = MARKER_KINDS[$('#mkKind', b).value][0]; };
    $('#mkSave', b).onclick = async () => {
      const d = { label: lab.value || MARKER_KINDS[$('#mkKind', b).value][0], kind: $('#mkKind', b).value, lat: parseFloat($('#mkLat', b).value), lon: parseFloat($('#mkLon', b).value), notes: $('#mkNotes', b).value, permanent: $('#mkPerm', b)?.checked };
      if (m.id) await put('/api/markers/' + m.id, d); else await post('/api/markers', d);
      closeModal();
    };
    if (m.id) $('#mkDel', b).onclick = async () => { if (confirm('Delete this location?')) { await del('/api/markers/' + m.id); closeModal(); } };
  });
}
function stationIcon(s) {
  const st = s.checkin ? s.checkin.status : null; const color = st ? stColor(st) : '#2c3e50';
  const stale = ago(s.ts) > 30;
  return L.divIcon({ className: '', html: `<svg width="18" height="18" viewBox="0 0 18 18"><circle cx="9" cy="9" r="7" fill="${color}" stroke="#fff" stroke-width="2" opacity="${stale ? .55 : 1}"/></svg>`, iconSize: [18, 18], iconAnchor: [9, 9] });
}
async function loadMap() {
  if (!S.map) return;
  const d = await api('/api/map' + ($('#showAllStations').checked ? '?all=1' : ''));
  S.mapData = d; stationsCache = d.stations;
  S.layers.st.clearLayers(); S.layers.tr.clearLayers(); S.layers.mk.clearLayers(); S.markerRefs = {};
  d.stations.forEach(s => {
    const c = s.checkin;
    const label = s.callsign + (c && c.tactical ? ' · ' + c.tactical : '');
    const mk = L.marker([s.lat, s.lon], { icon: stationIcon(s) }).addTo(S.layers.st)
      .bindTooltip(esc(label), { permanent: true, direction: 'right', offset: [8, 0], className: 'lbl' })
      .bindPopup(`<b>${esc(s.callsign)}</b> ${c ? esc(c.name || '') : ''}<br>${c ? 'Status: <b>' + esc(c.status) + '</b><br>' : ''}${c && c.location ? 'Location: ' + esc(c.location) + '<br>' : ''}${c && c.notes ? 'Notes: ' + esc(c.notes) + '<br>' : ''}
        ${s.lat.toFixed(5)}, ${s.lon.toFixed(5)}<br>Source: ${esc(s.source)} · ${fmtDT(s.ts)} (${Math.round(ago(s.ts))} min ago)${s.speed ? '<br>' + s.speed + ' km/h ' + s.course + '°' : ''}${s.comment ? '<br><i>' + esc(s.comment) + '</i>' : ''}`);
    S.markerRefs[s.callsign] = mk;
    if ($('#showTracks').checked && s.track && s.track.length > 1) L.polyline(s.track.map(t => [t.lat, t.lon]), { color: c ? stColor(c.status) : '#2c3e50', weight: 2, opacity: .6 }).addTo(S.layers.tr);
  });
  d.markers.forEach(m => {
    const [name, color] = MARKER_KINDS[m.kind] || MARKER_KINDS.other;
    const mk = L.marker([m.lat, m.lon], { draggable: true, icon: L.divIcon({ className: '', html: `<div class="pin" style="background:${color}">${esc(m.label)}</div>`, iconSize: null, iconAnchor: [12, 12] }) }).addTo(S.layers.mk);
    mk.bindPopup(`<b>${esc(m.label)}</b> (${name})<br>${esc(m.notes || '')}<br>${m.lat.toFixed(5)}, ${m.lon.toFixed(5)}<br><a href="#" data-edit-marker="${m.id}">Edit</a>`);
    mk.on('dragend', async () => { const p = mk.getLatLng(); await put('/api/markers/' + m.id, { lat: p.lat, lng: p.lng, lon: p.lng }); });
  });
  $('#stationList').innerHTML = d.stations.map(s => `<div class="it" data-loc="${esc(s.callsign)}"><span class="dot ${ago(s.ts) < 30 ? 'fresh' : 'stale'}"></span><b>${esc(s.callsign)}</b><span class="sub">${esc(s.checkin ? s.checkin.status : '')} · ${Math.round(ago(s.ts))}m · ${esc(s.source)}</span></div>`).join('') || '<div class="hint">No positions yet. Stations on the roster are tracked automatically via APRS-IS. You can also type a grid square or "lat, lon" in a station\'s Location.</div>';
  $('#markerList').innerHTML = d.markers.map(m => `<div class="it" data-mk="${m.id}"><span class="pin" style="background:${(MARKER_KINDS[m.kind] || MARKER_KINDS.other)[1]}">${esc(m.label)}</span><span class="sub">${esc(m.notes || '')}</span></div>`).join('') || '<div class="hint">None yet. Use “Drop location”.</div>';
  renderRoster();
}
function locate(call) { const m = S.markerRefs && S.markerRefs[call]; if (m) { S.map.setView(m.getLatLng(), Math.max(S.map.getZoom(), 13)); m.openPopup(); } }
$('#stationList').onclick = e => { const it = e.target.closest('[data-loc]'); if (it) locate(it.dataset.loc); };
$('#markerList').onclick = e => { const it = e.target.closest('[data-mk]'); if (!it) return; const m = S.mapData.markers.find(x => x.id == it.dataset.mk); S.map.setView([m.lat, m.lon], Math.max(S.map.getZoom(), 13)); };
document.addEventListener('click', e => { const id = e.target.dataset && e.target.dataset.editMarker; if (id) { e.preventDefault(); markerDialog(S.mapData.markers.find(x => x.id == id)); } });

/* ---------------------------------------------------------------- forms */
async function loadFormDefs() {
  S.formdefs = await api('/api/formdefs');
  $('#builtinForms').innerHTML = Object.entries(S.formdefs.builtin).map(([k, d]) => `<button data-newform="${k}">+ ${esc(d.name)}</button>`).join('');
  const mc = Object.values(S.formdefs.mcforms);
  $('#mcForms').innerHTML = mc.map(f => `<div class="it" data-mcf="${esc(f.id)}"><b>${esc(f.id)}</b> ${esc(f.title)}</div>`).join('') || '<div class="hint">No MCForms installed yet. Click below to download the current set from SitRepNet.com.</div>';
  const wl = await api('/api/wlforms'); S.wlTemplates = wl.templates;
  $('#wlDir').textContent = wl.dir ? 'Library: ' + wl.dir : 'No Winlink Standard Forms folder found. Install Pat (pat templates update) or set the folder in Settings.';
  renderWlForms();
}
function renderWlForms() {
  const q = $('#wlSearch').value.toLowerCase(); let last = null; let html = '';
  for (const t of (S.wlTemplates || [])) {
    if (q && !(t.name + ' ' + t.folder).toLowerCase().includes(q)) continue;
    if (t.folder !== last) { html += `<div class="folder">${esc(t.folder)}</div>`; last = t.folder; }
    html += `<div class="it" data-wlt="${esc(t.path)}">${esc(t.name)}</div>`;
  }
  $('#wlForms').innerHTML = html || '<div class="hint">No forms.</div>';
}
$('#wlSearch').oninput = renderWlForms;
$('#wlForms').onclick = e => { const it = e.target.closest('[data-wlt]'); if (it) window.open('/wlforms/open?tpl=' + encodeURIComponent(it.dataset.wlt), '_blank', 'width=1000,height=900'); };
$('#builtinForms').onclick = e => { const k = e.target.dataset.newform; if (k) openForm({ form_type: k, data: {} }); };
$('#mcForms').onclick = e => { const it = e.target.closest('[data-mcf]'); if (it) openForm({ form_type: 'MCF:' + it.dataset.mcf, data: {} }); };
$('#btnMcfDl').onclick = async () => { toast('Downloading MCForms…'); const r = await post('/api/mcforms/download'); toast(`Installed ${r.count} MCForms`); loadFormDefs(); };
$('#formsAll').onchange = loadFormLog;
window.addEventListener('message', e => { if (e.data && e.data.type === 'wlform') afterWlForm(e.data.id); });
try { new BroadcastChannel('ares').onmessage = e => { if (e.data && e.data.type === 'wlform') afterWlForm(e.data.id); }; } catch (e) { }
let lastWl = 0;
async function afterWlForm(id) { if (id === lastWl) return; lastWl = id; showTab('forms'); const f = await api('/api/forms/' + id); sendFormDialog(f); }

async function loadForms() { if (!S.formdefs) await loadFormDefs(); loadFormLog(); }
async function loadFormLog() {
  const rows = await api('/api/forms' + ($('#formsAll').checked ? '?net_id=all' : ''));
  $('#formLog tbody').innerHTML = rows.map(r => `<tr><td>${esc(r.number || '')}</td><td>${esc(r.form_name)}</td><td>${esc(r.title)}</td><td>${esc(r.direction || '')}</td><td>${fmtDT(r.created_at)}</td>
    <td style="white-space:nowrap"><button class="small" data-fopen="${r.id}">Open</button> <button class="small" data-fprint="${r.id}">Print</button> <button class="small" data-fsend="${r.id}">Send…</button> <button class="small" data-fdup="${r.id}">Copy</button> <button class="small" data-fdel="${r.id}">✕</button></td></tr>`).join('') || '<tr><td colspan="6" class="hint">No forms logged for this net yet. Use “Create New”.</td></tr>';
}
$('#formLog').onclick = async e => {
  const d = e.target.dataset;
  if (d.fopen) { const f = await api('/api/forms/' + d.fopen); if (f.form_type.startsWith('WL:')) sendFormDialog(f); else openForm(f); }
  if (d.fprint) window.open('/api/forms/' + d.fprint + '/print', '_blank');
  if (d.fsend) sendFormDialog(await api('/api/forms/' + d.fsend));
  if (d.fdup) { const f = await api('/api/forms/' + d.fdup); delete f.id; openForm({ form_type: f.form_type, data: f.data }); }
  if (d.fdel && confirm('Delete this form from the log?')) { await del('/api/forms/' + d.fdel); loadFormLog(); }
};

function autoVal(a) {
  const s = S.settings, now = new Date();
  return { date: now.toISOString().slice(0, 10), time: now.toTimeString().slice(0, 5), operator: s.operator_name || s.mycall, org: s.org_title, mycall: s.mycall, operator_call: [s.operator_name, s.mycall].filter(Boolean).join(', ') }[a] || '';
}
function fieldHtml(fd, v) {
  const id = 'f_' + fd.k;
  if (fd.type === 'section') return `<div class="fsec">${esc(fd.label)}</div>`;
  if (fd.type === 'textarea') return `<label class="wide">${esc(fd.label)}<textarea id="${id}" rows="${fd.rows || 4}" ${fd.upper ? 'style="text-transform:uppercase"' : ''}>${esc(v)}</textarea>${fd.help ? '<span class="hint">' + esc(fd.help) + '</span>' : ''}</label>`;
  if (fd.type === 'select') return `<label>${esc(fd.label)}<select id="${id}">${fd.options.map(o => `<option ${o === v ? 'selected' : ''}>${esc(o)}</option>`).join('')}</select></label>`;
  if (fd.type === 'table') {
    const rows = (v && v.length ? v : [{}, {}, {}]);
    return `<div class="wide"><div class="fsec">${esc(fd.label)} ${fd.import_from ? `<button type="button" class="small" data-import="${fd.k}" data-from="${fd.import_from}">Import from net</button>` : ''} <button type="button" class="small" data-addrow="${fd.k}">+ row</button></div>
      <table class="ftab" id="${id}"><thead><tr>${fd.cols.map(c => `<th>${esc(c.label)}</th>`).join('')}</tr></thead><tbody>${rows.map(r => tableRow(fd, r)).join('')}</tbody></table></div>`;
  }
  return `<label>${esc(fd.label)}<input id="${id}" type="${fd.type === 'text' ? 'text' : fd.type}" value="${esc(v)}">${fd.help ? '<span class="hint">' + esc(fd.help) + '</span>' : ''}</label>`;
}
const tableRow = (fd, r) => `<tr>${fd.cols.map(c => `<td><input data-col="${c.k}" value="${esc(r[c.k] || '')}"></td>`).join('')}</tr>`;
function collect(def, b) {
  const data = {};
  def.fields.forEach(fd => {
    if (fd.type === 'section') return;
    const el = $('#f_' + fd.k, b); if (!el) return;
    if (fd.type === 'table') data[fd.k] = $$('tbody tr', el).map(tr => Object.fromEntries($$('input', tr).map(i => [i.dataset.col, i.value]))).filter(r => Object.values(r).some(x => x.trim()));
    else data[fd.k] = fd.upper ? el.value.toUpperCase() : el.value;
  });
  return data;
}

function openForm(f) {
  if (f.form_type.startsWith('MCF:')) return openMcForm(f);
  const def = S.formdefs.builtin[f.form_type];
  const data = f.data || {};
  const body = def.fields.map(fd => { let v = data[fd.k]; if (v === undefined) v = fd.auto ? autoVal(fd.auto) : (fd.default || ''); return fieldHtml(fd, v); }).join('');
  modal((f.id ? 'Edit ' : 'New ') + def.name, `<div class="fgrid">${body}</div>
    <div class="row" style="margin-top:12px"><button class="primary" id="fSave">Save to log</button><button id="fSaveSend">Save &amp; send…</button><span class="grow"></span><span class="hint">${f.id ? 'Form #' + esc(f.number) : ''}</span></div>`, b => {
    b.addEventListener('click', async e => {
      const t = e.target.dataset;
      if (t.addrow) { const fd = def.fields.find(x => x.k === t.addrow); $('#f_' + fd.k + ' tbody', b).insertAdjacentHTML('beforeend', tableRow(fd, {})); }
      if (t.import) importTable(def.fields.find(x => x.k === t.import), t.from, b);
    });
    if (f.form_type === 'RADIOGRAM') {
      const upd = () => { const words = $('#f_text', b).value.trim().split(/\s+/).filter(Boolean); $('#f_check', b).value = (words[0] || '').toUpperCase() === 'ARL' ? 'ARL ' + words.length : words.length; };
      $('#f_text', b).addEventListener('input', upd);
      if (!f.id) { const d = new Date(); $('#f_time_filed', b).value = d.toISOString().slice(11, 13) + d.toISOString().slice(14, 16) + 'Z'; $('#f_date_filed', b).value = d.toLocaleString('en-US', { month: 'short', timeZone: 'UTC' }).toUpperCase() + ' ' + d.getUTCDate(); }
    }
    const save = async () => { const d = collect(def, b); return f.id ? put('/api/forms/' + f.id, { data: d }) : post('/api/forms', { form_type: f.form_type, data: d }); };
    $('#fSave', b).onclick = async () => { await save(); closeModal(); toast('Form saved'); loadFormLog(); };
    $('#fSaveSend', b).onclick = async () => { const r = await save(); loadFormLog(); sendFormDialog(r); };
  });
}
async function importTable(fd, from, b) {
  const tb = $('#f_' + fd.k + ' tbody', b); let rows = [];
  if (from === 'checkins') rows = S.checkins.map(c => ({ name: [c.callsign, c.name].filter(Boolean).join(' '), position: c.tactical || 'Radio Operator', agency: S.settings.org_title }));
  if (from === 'activity') rows = (await api('/api/activity')).slice().reverse().map(a => ({ dt: fmtDT(a.ts), activity: a.text }));
  if (from === 'traffic') {
    const acts = (await api('/api/activity')).slice().reverse().filter(a => ['winlink', 'js8', 'form', 'note', 'checkin', 'status'].includes(a.kind));
    rows = acts.map(a => ({ time: fmtT(a.ts), from_call: a.callsign || '', to_call: a.callsign ? (S.settings.mycall || 'NCS') : '', message: a.text }));
  }
  const existing = $$('tr', tb).filter(tr => $$('input', tr).some(i => i.value.trim()));
  tb.innerHTML = ''; existing.forEach(tr => tb.appendChild(tr));
  tb.insertAdjacentHTML('beforeend', rows.map(r => tableRow(fd, r)).join(''));
}

function openMcForm(f) {
  const id = f.form_type.slice(4); const frm = S.formdefs.mcforms[id];
  if (!frm) return toast('MCForm ' + id + ' is not installed', true);
  const ans = (f.data && f.data.answers) || {}; let qi = 0; let html = '';
  for (const it of frm.items) {
    if (it.type === 'heading') html += `<div class="mch">${esc(it.label)}</div>`;
    else if (it.type === 'info') html += `<div class="mci">${esc(it.label)}</div>`;
    else if (it.type === 'text') html += `<label>${esc(it.label)}<input data-mt="${esc(it.tag)}" value="${esc(ans['t' + it.tag] || '')}"></label>`;
    else if (it.type === 'choice') {
      const cur = ans['q' + qi] || it.default || '';
      html += `<div class="mcq"><div class="q">${esc(it.label)}</div><select data-mq="${qi}"><option value="">—</option>${it.options.map(o => `<option value="${esc(o.code)}" ${o.code === cur ? 'selected' : ''}>${esc(o.code)} · ${esc(o.label)}</option>`).join('')}</select></div>`;
      qi++;
    }
  }
  modal(`${frm.id} ${frm.title}`, `${html}<div class="hint">Encoded: <code id="mcEnc"></code></div><div class="row"><button class="primary" id="mcSave">Save to log</button><button id="mcSend">Save &amp; send…</button></div>`, b => {
    const gather = () => { const a = {}; $$('[data-mq]', b).forEach(s => a['q' + s.dataset.mq] = s.value); $$('[data-mt]', b).forEach(i => a['t' + i.dataset.mt] = i.value); return a; };
    const enc = () => { const a = gather(); let codes = ''; $$('[data-mq]', b).forEach(s => codes += s.value || '?'); const t = $$('[data-mt]', b).filter(i => i.value.trim()).map(i => `[${i.dataset.mt}]${i.value.trim()}`); $('#mcEnc', b).textContent = frm.id + ' ' + codes + (t.length ? ' ' + t.join(' ') : ''); };
    b.addEventListener('change', enc); b.addEventListener('input', enc); enc();
    const save = () => f.id ? put('/api/forms/' + f.id, { data: { answers: gather() } }) : post('/api/forms', { form_type: f.form_type, data: { answers: gather() } });
    $('#mcSave', b).onclick = async () => { await save(); closeModal(); toast('Saved'); loadFormLog(); };
    $('#mcSend', b).onclick = async () => { const r = await save(); loadFormLog(); sendFormDialog(r); };
  });
}

async function sendFormDialog(f) {
  const t = await api('/api/forms/' + f.id + '/text');
  const isMc = f.form_type.startsWith('MCF:'); const isWl = f.form_type.startsWith('WL:');
  const to = isWl ? (f.data.to || '') : '';
  const body = isWl ? f.data.body : t.text;
  const js8text = isMc ? f.data.compact : '';
  modal('Send ' + f.form_name, `<div class="seg" id="sendVia"><button data-via="winlink" class="${isMc ? '' : 'active'}">Winlink</button><button data-via="js8" class="${isMc ? 'active' : ''}">JS8Call</button><button data-via="print">Print</button></div>
    <div id="viaWl" class="${isMc ? 'hidden' : ''}" style="margin-top:10px">
      <div class="grid2"><label>To (callsigns or emails, comma separated)<input id="sTo" value="${esc(to)}"></label><label>Cc<input id="sCc" value="${esc(isWl ? f.data.cc || '' : '')}"></label></div>
      <label>Subject<input id="sSubj" value="${esc(t.subject)}"></label>
      <label>Body<textarea id="sBody" rows="14">${esc(body)}</textarea></label>
      ${isWl ? `<div class="hint">Includes Winlink form attachment <code>${esc(f.data.xml_name)}</code> so Winlink Express users see the formatted form.</div>` : ''}
      <button class="primary" id="sQueue">Queue in Winlink Outbox</button>
    </div>
    <div id="viaJs8" class="${isMc ? '' : 'hidden'}" style="margin-top:10px">
      <label>To (@GROUP or callsign; blank to send as typed)<input id="jTo" value="${isMc ? '@SITREP' : ''}"></label>
      <label>Text<textarea id="jText" rows="4">${esc(js8text || t.text.slice(0, 500))}</textarea></label>
      <button class="primary" id="jSend">Send via JS8Call</button>
    </div>`, b => {
    $('#sendVia', b).onclick = e => { const v = e.target.dataset.via; if (!v) return; if (v === 'print') return window.open('/api/forms/' + f.id + '/print', '_blank');
      $$('#sendVia button', b).forEach(x => x.classList.toggle('active', x === e.target)); $('#viaWl', b).classList.toggle('hidden', v !== 'winlink'); $('#viaJs8', b).classList.toggle('hidden', v !== 'js8'); };
    $('#sQueue', b).onclick = async () => { await post('/api/forms/' + f.id + '/send', { via: 'winlink', to: $('#sTo', b).value, cc: $('#sCc', b).value, subject: $('#sSubj', b).value, body: $('#sBody', b).value }); closeModal(); toast('Queued in Winlink outbox'); };
    $('#jSend', b).onclick = async () => { await post('/api/forms/' + f.id + '/send', { via: 'js8', to: $('#jTo', b).value, text: $('#jText', b).value }); closeModal(); toast('Sent to JS8Call'); };
  });
}

/* ---------------------------------------------------------------- winlink */
$('#boxSeg').onclick = e => { const bx = e.target.dataset.box; if (!bx) return; S.box = bx; $$('#boxSeg button').forEach(b => b.classList.toggle('active', b === e.target)); loadBox(); };
const kb = n => n > 1024 ? (n / 1024).toFixed(1) + ' KB' : (n || 0) + ' B';
async function loadBox() {
  if (S.box === 'nodes') return renderNodes();
  if (S.box === 'pending') {
    const rows = await api('/api/winlink/pending');
    $('#boxView').innerHTML = `<p class="hint">Messages waiting on the Winlink server that you chose not to download yet. Tick the ones you want and connect with “Download selected”.</p>
      <table class="data"><thead><tr><th></th><th>From</th><th>Subject</th><th>Size</th><th>MID</th><th>Seen</th></tr></thead><tbody>${rows.map(r => `<tr><td><input type="checkbox" data-pmid="${esc(r.mid)}" checked></td><td>${esc(r.from_addr || '?')}</td><td>${esc(r.subject || '(subject not provided by server)')}</td><td>${kb(r.size)}</td><td class="mono">${esc(r.mid)}</td><td>${fmtDT(r.seen_at)}</td></tr>`).join('') || '<tr><td colspan="6" class="hint">Nothing listed.</td></tr>'}</tbody></table>
      <div class="row"><button class="primary" id="btnDlSel">Download selected</button><button id="btnClrPend">Clear list</button></div>`;
    $('#btnDlSel').onclick = () => wlConnect('list', $$('[data-pmid]').filter(c => c.checked).map(c => c.dataset.pmid));
    $('#btnClrPend').onclick = async () => { await del('/api/winlink/pending'); loadBox(); };
    return;
  }
  const r = await api('/api/messages?box=' + S.box);
  const c = r.counts; $('#wlBadge').textContent = (c.outbox || '') ? c.outbox : '';
  $$('#boxSeg button').forEach(b => { const n = c[b.dataset.box]; b.textContent = b.textContent.replace(/ \(\d+\)$/, '') + (n ? ` (${n})` : ''); });
  const other = S.box === 'inbox' ? 'From' : 'To';
  $('#boxView').innerHTML = `<table class="data"><thead><tr><th>Date</th><th>${other}</th><th>Subject</th><th>Size</th></tr></thead><tbody>${r.messages.map(m => `<tr class="clickable ${m.status === 'unread' ? 'unread' : ''}" data-msg="${m.id}"><td>${esc(fmtDT(m.date) || m.date)}</td><td>${esc(S.box === 'inbox' ? m.from_addr : m.to_addrs)}</td><td>${esc(m.subject)}</td><td>${kb(m.size)}</td></tr>`).join('') || '<tr><td colspan="4" class="hint">Empty</td></tr>'}</tbody></table>`;
}
$('#boxView').addEventListener('click', async e => { const tr = e.target.closest('[data-msg]'); if (tr) showMsg(tr.dataset.msg); });
async function showMsg(id) {
  const m = await api('/api/messages/' + id); S.currentMsg = m;
  $('#msgView').innerHTML = `<div class="msghead"><div><b>From</b>${esc(m.from_addr)}</div><div><b>To</b>${esc(m.to_addrs)}</div>${m.cc_addrs ? `<div><b>Cc</b>${esc(m.cc_addrs)}</div>` : ''}<div><b>Subject</b>${esc(m.subject)}</div><div><b>Date</b>${esc(m.date)}</div><div><b>MID</b><span class="mono">${esc(m.mid)}</span></div></div>
   ${m.files.length ? '<div class="hint">Attachments: ' + m.files.map((f, i) => `<a href="/api/messages/${m.id}/file/${i}">${esc(f.name)}</a> (${kb(f.size)})`).join(', ') + '</div>' : ''}
   <div class="row">${m.has_form ? `<button class="primary" onclick="window.open('/wlforms/view/${m.id}','_blank')">View form</button>` : ''}<button id="mReply">Reply</button><button id="mFwd">Forward</button><button id="mLog">Log as ICS-213</button><button class="danger" id="mDel">Delete</button></div>
   <div class="msgbody">${esc(m.body)}</div>`;
  $('#mReply').onclick = () => compose({ to: m.from_addr, subject: 'Re: ' + m.subject, body: '\n\n--- ' + m.from_addr + ' wrote:\n' + m.body });
  $('#mFwd').onclick = () => compose({ subject: 'Fw: ' + m.subject, body: '\n\n--- Forwarded message from ' + m.from_addr + ':\n' + m.body });
  $('#mDel').onclick = async () => { if (confirm('Delete message?')) { await del('/api/messages/' + m.id); $('#msgView').innerHTML = ''; } };
  $('#mLog').onclick = async () => { await post('/api/forms', { form_type: 'ICS213', data: { direction: m.box === 'inbox' ? 'Incoming' : 'Outgoing', via: 'Winlink', to: m.to_addrs, from: m.from_addr, subject: m.subject, message: m.body, date: (m.date || '').slice(0, 10).replace(/\//g, '-'), time: (m.date || '').slice(11, 16) } }); toast('Logged as ICS-213'); };
}
function compose(p = {}) {
  modal('New Winlink message', `<div class="grid2"><label>To<input id="cTo" value="${esc(p.to || '')}"></label><label>Cc<input id="cCc"></label></div>
    <label>Subject<input id="cSubj" value="${esc(p.subject || '')}"></label><label>Message<textarea id="cBody" rows="14">${esc(p.body || '')}</textarea></label>
    <button class="primary" id="cSend">Queue in Outbox</button>`, b => {
    $('#cTo', b).focus();
    $('#cSend', b).onclick = async () => { await post('/api/messages', { to: $('#cTo', b).value, cc: $('#cCc', b).value, subject: $('#cSubj', b).value, body: $('#cBody', b).value }); closeModal(); toast('Queued'); loadBox(); };
  });
}
$('#btnCompose').onclick = () => compose();

let nodesCache = [];
async function loadNodes() {
  nodesCache = await api('/api/nodes');
  $('#wlGateway').innerHTML = '<option value="">— manual entry —</option>' + nodesCache.map(n => `<option value="${n.id}">${n.favorite ? '★ ' : ''}${esc(n.callsign)} · ${esc(n.frequency)} kHz · ${esc(n.mode || '')} ${esc(n.grid || '')}</option>`).join('');
}
$('#wlGateway').onchange = () => { const n = nodesCache.find(x => x.id == $('#wlGateway').value); if (n) { $('#wlGwCall').value = n.callsign; $('#wlGwFreq').value = n.frequency; } };
function renderNodes() {
  $('#boxView').innerHTML = `<div class="toolbar"><button id="nAdd">+ Add gateway</button><button id="nImport">Import ARDOP list from Pat</button><input id="nFilter" placeholder="Filter (call, grid, notes)…"><span class="hint">★ favorites appear first in the Connect list.</span></div>
   <div class="tablewrap" style="max-height:60vh"><table class="data" id="nodeTable"><thead><tr><th>★</th><th>Callsign</th><th>Dial kHz</th><th>Mode</th><th>BW</th><th>Grid</th><th>Distance / Location</th><th>Hours</th><th>Notes</th><th></th></tr></thead><tbody></tbody></table></div>`;
  const draw = () => {
    const q = ($('#nFilter').value || '').toLowerCase();
    $('#nodeTable tbody').innerHTML = nodesCache.filter(n => !q || JSON.stringify(n).toLowerCase().includes(q)).slice(0, 800).map(n => `<tr>
      <td><input type="checkbox" data-nid="${n.id}" data-f="favorite" ${n.favorite ? 'checked' : ''}></td>
      ${['callsign', 'frequency', 'mode', 'bandwidth', 'grid', 'location', 'hours', 'notes'].map(k => `<td><input data-nid="${n.id}" data-f="${k}" value="${esc(n[k])}"></td>`).join('')}
      <td><button class="small" data-nuse="${n.id}">Use</button> <button class="small" data-ndel="${n.id}">✕</button></td></tr>`).join('');
  };
  draw();
  $('#nFilter').oninput = draw;
  $('#nAdd').onclick = async () => { await post('/api/nodes', { callsign: 'NEW', mode: 'ARDOP', favorite: true }); await loadNodes(); draw(); };
  $('#nImport').onclick = async () => { toast('Importing gateway list from Pat…'); const r = await post('/api/nodes/import_pat', { mode: 'ardop' }); toast(`Imported ${r.imported} gateways`); await loadNodes(); draw(); };
  $('#nodeTable').onchange = async e => { const el = e.target; if (!el.dataset.nid) return; await put('/api/nodes/' + el.dataset.nid, { [el.dataset.f]: el.type === 'checkbox' ? el.checked : el.value }); await loadNodes(); };
  $('#nodeTable').onclick = async e => {
    const d = e.target.dataset;
    if (d.ndel && confirm('Delete gateway?')) { await del('/api/nodes/' + d.ndel); await loadNodes(); draw(); }
    if (d.nuse) { $('#wlTransport').value = 'ardop'; $('#wlTransport').onchange(); $('#wlGateway').value = d.nuse; $('#wlGateway').onchange(); toast('Gateway selected'); }
  };
}
$('#wlTransport').onchange = () => {
  const t = $('#wlTransport').value;
  $('#wlGwWrap').classList.toggle('hidden', t !== 'ardop'); $('#wlManual').classList.toggle('hidden', t === 'telnet');
  $('#wlHostWrap').classList.toggle('hidden', t !== 'p2p');
};
async function wlConnect(mode, mids) {
  const t = $('#wlTransport').value;
  const body = { mode: mode || $('#wlMode').value, mids };
  if (t === 'ardop') Object.assign(body, { transport: 'ardop', gateway: $('#wlGwCall').value, freq: $('#wlGwFreq').value });
  else if (t === 'telnet') Object.assign(body, { transport: 'telnet', host: 'cms.winlink.org', port: 8772 });
  else { const [h, p] = $('#wlHost').value.split(':'); Object.assign(body, { transport: 'telnet', host: h, port: parseInt(p || '8774'), gateway: $('#wlGwCall').value }); }
  await post('/api/winlink/connect', body); toast('Winlink session started');
}
$('#btnWlConnect').onclick = () => wlConnect();
$('#btnWlAbort').onclick = () => post('/api/winlink/abort');
async function loadWlStatus() {
  const s = await api('/api/winlink/status');
  $('#wlLog').textContent = s.log.join('\n'); $('#wlLog').scrollTop = 1e9;
  renderWlState(s);
}
function renderWlState(s) {
  $('#wlState').textContent = 'Status: ' + s.state; setChip('#chipWL', s.state);
  if (s.awaiting && s.awaiting.length && !$('#selDlg')) selectionDialog(s.awaiting);
}
function selectionDialog(props) {
  showTab('winlink');
  modal('Messages waiting on the server', `<div id="selDlg"><p>Choose which messages to download now. Unchecked messages stay on the server for later.</p>
   <table class="data"><thead><tr><th><input type="checkbox" id="selAll" checked></th><th>From</th><th>Subject</th><th>Size</th><th>MID</th></tr></thead><tbody>
   ${props.map(p => `<tr class="selrow"><td><input type="checkbox" data-smid="${esc(p.mid)}" checked></td><td>${esc(p.from || '?')}</td><td>${esc(p.subject || '(subject not sent by server)')}</td><td>${kb(p.usize)} <span class="hint">(${kb(p.csize)} over air)</span></td><td class="mono">${esc(p.mid)}</td></tr>`).join('')}
   </tbody></table><div class="row" style="margin-top:10px"><button class="primary" id="selGo">Download selected</button><button id="selNone">Leave all on server</button><span class="hint" id="selTot"></span></div></div>`, b => {
    const tot = () => { const n = $$('[data-smid]', b).filter(c => c.checked).map(c => props.find(p => p.mid === c.dataset.smid)).reduce((a, p) => a + p.csize, 0); $('#selTot', b).textContent = 'Selected: ' + kb(n) + ' over the air'; };
    b.addEventListener('change', tot); tot();
    $('#selAll', b).onchange = e => $$('[data-smid]', b).forEach(c => c.checked = e.target.checked);
    const send = async (all) => { const ch = {}; $$('[data-smid]', b).forEach(c => ch[c.dataset.smid] = (all !== false && c.checked) ? '+' : '='); await post('/api/winlink/select', { choices: ch }); closeModal(); };
    $('#selGo', b).onclick = () => send(true); $('#selNone', b).onclick = () => send(false);
  });
}


/* ---------------------------------------------------------------- JS8 */
function decodeMcf(text) {
  if (!S.formdefs) return '';
  const m = /(F![\w]+)\s+([0-9A-Z?]+)((?:\s+\[\w+\][^\[]*)*)/.exec(text || ''); if (!m) return '';
  const frm = S.formdefs.mcforms[m[1]]; if (!frm) return '';
  const qs = frm.items.filter(i => i.type === 'choice'); const codes = m[2];
  return frm.title + ': ' + qs.map((q, i) => { const o = q.options.find(o => o.code === codes[i]); return q.label + ' ' + (o ? o.label : '?'); }).join('; ') + (m[3] || '');
}
async function loadJs8() {
  if (!S.formdefs) await loadFormDefs().catch(() => { });
  const rows = await api('/api/js8');
  $('#js8Table tbody').innerHTML = rows.map(r => { const dec = decodeMcf(r.text); return `<tr><td>${fmtDT(r.ts)}</td><td>${esc(r.kind)}</td><td class="call">${esc(r.from_call)}</td><td>${esc(r.to_call)}</td><td>${r.snr ?? ''}</td><td>${esc(r.text)}${dec ? '<div class="hint">' + esc(dec) + '</div>' : ''}</td></tr>`; }).join('') || '<tr><td colspan="6" class="hint">No JS8 traffic yet.</td></tr>';
}
$('#js8Form').onsubmit = async e => { e.preventDefault(); const to = $('#js8To').value.trim(); const t = $('#js8Text').value.trim(); if (!t) return; await post('/api/js8/send', { text: to ? to + ' ' + t : t }); $('#js8Text').value = ''; loadJs8(); };

/* ---------------------------------------------------------------- reports */
async function loadNets() {
  const rows = await api('/api/nets');
  $('#netsTable tbody').innerHTML = rows.map(n => `<tr><td><b>${esc(n.name)}</b></td><td>${esc(n.ncs)}</td><td>${esc(n.frequency)}</td><td>${fmtDT(n.opened_at)}</td><td>${n.closed_at ? fmtDT(n.closed_at) : '<b style="color:#b03a2e">OPEN</b>'}</td><td>${n.checkins}</td>
   <td><button class="small" onclick="window.open('/api/report/${n.id}','_blank')">View / Print</button> <a class="small" href="/api/report/${n.id}?download=1">Download</a></td></tr>`).join('') || '<tr><td colspan="7" class="hint">No nets yet.</td></tr>';
}

/* ---------------------------------------------------------------- settings */
function fillSettings() {
  const f = $('#settingsForm');
  for (const el of f.elements) { if (!el.name) continue; const v = S.settings[el.name] ?? ''; if (el.type === 'checkbox') el.checked = v === '1'; else el.value = v; }
}
$('#settingsForm').onsubmit = async e => {
  e.preventDefault(); const d = {};
  for (const el of e.target.elements) { if (!el.name) continue; d[el.name] = el.type === 'checkbox' ? (el.checked ? '1' : '0') : el.value; }
  S.settings = await post('/api/settings', d); renderHeader(); $('#setSaved').textContent = 'Saved ' + new Date().toLocaleTimeString(); toast('Settings saved');
  if (S.map) setBaseLayer();
  S.formdefs = null;
};

/* ---------------------------------------------------------------- live events */
let debounce = {};
const later = (k, fn, ms = 250) => { clearTimeout(debounce[k]); debounce[k] = setTimeout(fn, ms); };
function connectEvents() {
  const es = new EventSource('/api/events');
  es.onmessage = ev => {
    const m = JSON.parse(ev.data); const d = m.data;
    switch (m.type) {
      case 'checkins': case 'net': later('state', loadState); later('map', () => S.map && loadMap(), 600); break;
      case 'activity': later('act', loadActivity); break;
      case 'position': case 'markers': later('map', () => S.map ? loadMap() : api('/api/map').then(r => { stationsCache = r.stations; renderRoster(); }), 500); break;
      case 'aprs_status': setChip('#chipAPRS', d.status); break;
      case 'js8_status': setChip('#chipJS8', d.status); $('#js8Status').textContent = d.status + (d.info && d.info.callsign ? ' · ' + d.info.callsign : '') + (d.info && d.info.dial ? ' · ' + (d.info.dial / 1000).toFixed(1) + ' kHz' : ''); break;
      case 'js8': later('js8', loadJs8); later('act', loadActivity); break;
      case 'forms': later('forms', loadFormLog); later('act', loadActivity); break;
      case 'messages': later('box', loadBox); later('act', loadActivity); break;
      case 'winlink_log': { const el = $('#wlLog'); el.textContent += (el.textContent ? '\n' : '') + d; el.scrollTop = 1e9; break; }
      case 'winlink_status': renderWlState(d); break;
      case 'settings': S.settings = d; renderHeader(); break;
      case 'tiles_seed': showSeed(d); break;
      case 'tiles_status': setTileNet(d.online); break;
    }
    if (['checkin', 'status'].includes(m.type)) later('act', loadActivity);
  };
  es.onerror = () => { es.close(); setTimeout(connectEvents, 3000); };
}

/* ---------------------------------------------------------------- boot */
(async () => {
  await loadState();
  api('/api/map').then(r => { stationsCache = r.stations; renderRoster(); });
  connectEvents();
  $('#wlTransport').onchange();
  let t = 'net'; try { t = localStorage.getItem('ares.tab') || 'net'; } catch (e) { }
  showTab(t);
  if (!S.settings.mycall) { showTab('settings'); toast('Welcome! Set your organization title and callsign to get started.'); }
})();

/* ================================================================ VFO + waterfall strips
   One shared audio capture (the radio's sound card, chosen in the strip) feeds a
   waterfall on the Winlink and JS8Call tabs. Audio stays in this browser. */
const JS8_BANDS = [['80', 3578000], ['40', 7078000], ['30', 10130000], ['20', 14078000], ['15', 21078000], ['10', 28078000]];
const WF_MAX_HZ = 3000;
const STRIPS = [];
let lastVfo = null;

function fmtVfo(hz) {
  if (!hz) return '--.---.---';
  const s = String(Math.round(hz)).padStart(7, '0');
  return s.slice(0, -6) + '.' + s.slice(-6, -3) + '.' + s.slice(-3);
}
function buildStrip(el) {
  const js8 = el.dataset.mode === 'js8';
  el.innerHTML = `
    <div class="strip">
      <div class="vfo">
        <div class="vfo-freq mono">--.---.---</div>
        <div class="vfo-sub"><span class="vfo-mode"></span> <span class="vfo-tx hidden">TX</span> <span class="vfo-src"></span></div>
        <form class="row vfo-set"><input class="vfo-in" placeholder="kHz" inputmode="decimal"><button>Tune</button></form>
        ${js8 ? `<div class="bands">${JS8_BANDS.map(([b]) => `<button type="button" data-band="${b}">${b}m</button>`).join('')}</div>` : ''}
      </div>
      <div class="wfbox">
        <div class="wfscale">${[0, 500, 1000, 1500, 2000, 2500, 3000].map(f => `<span style="left:${f / WF_MAX_HZ * 100}%">${f}</span>`).join('')}</div>
        <div class="wfarea">
          <canvas class="wf" height="110"></canvas>
          <div class="wfmarks"></div>
          <div class="wfoff">Waterfall off — choose the radio's audio input and press Start</div>
        </div>
        <div class="wfctl">
          <button type="button" class="wf-start">Start</button>
          <select class="wf-dev" title="Audio input (the radio's sound card)"><option value="">Default input</option></select>
          <label class="inline" title="Waterfall contrast">Contrast <input type="range" class="wf-range" min="15" max="70" value="40"></label>
          <span class="hint wf-hint">${js8 ? 'Click the waterfall to move your JS8 transmit offset.' : 'Shaded area = ARDOP passband.'}</span>
        </div>
      </div>
    </div>`;
  const st = { el, js8, canvas: $('canvas', el), marks: $('.wfmarks', el) };
  STRIPS.push(st);
  $('.vfo-set', el).onsubmit = async e => {
    e.preventDefault(); const k = parseFloat($('.vfo-in', el).value); if (!k) return;
    await post('/api/rig', { freq: k * 1000 }); $('.vfo-in', el).value = ''; pollVfo();
  };
  if (js8) $('.bands', el).onclick = async e => {
    const b = e.target.dataset.band; if (!b) return;
    const r = await post('/api/js8/band', { band: b }); toast(`Tuned ${b}m JS8: ${(r.freq / 1e6).toFixed(3)} MHz via ${r.via.join(', ')}`); setTimeout(pollVfo, 400);
  };
  $('.wf-start', el).onclick = () => WF.running ? WF.stop() : WF.start();
  $('.wf-dev', el).onchange = e => { WF.setDevice(e.target.value); };
  $('.wf-range', el).oninput = e => { WF.range = +e.target.value; STRIPS.forEach(s => $('.wf-range', s.el).value = WF.range); };
  if (js8) $('.wfarea', el).onclick = async e => {
    if (!lastVfo || !lastVfo.js8) return toast('Connect JS8Call to set the offset', true);
    const r = $('.wfarea', el).getBoundingClientRect();
    const hz = Math.round((e.clientX - r.left) / r.width * WF_MAX_HZ / 10) * 10;
    await post('/api/js8/offset', { offset: Math.min(2950, Math.max(300, hz)) }); setTimeout(pollVfo, 300);
  };
}
function renderVfo(v) {
  lastVfo = v;
  for (const s of STRIPS) {
    const el = s.el;
    $('.vfo-freq', el).textContent = fmtVfo(v.freq);
    $('.vfo-freq', el).classList.toggle('dim', !v.freq);
    $('.vfo-mode', el).textContent = v.mode || '';
    $('.vfo-tx', el).classList.toggle('hidden', !v.ptt);
    $('.vfo-src', el).textContent = v.freq ? '· ' + v.source : (v.error || '');
    if (s.js8) $$('.bands button', el).forEach(b => {
      const f = JS8_BANDS.find(x => x[0] === b.dataset.band)[1];
      b.classList.toggle('active', !!v.freq && Math.abs(v.freq - f) < 5000);
    });
    drawMarks(s);
  }
}
function drawMarks(s) {
  let html = '';
  if (s.js8) {
    const off = lastVfo && lastVfo.js8 && lastVfo.js8.offset;
    if (off) html = `<div class="wfband tx" style="left:${off / WF_MAX_HZ * 100}%;width:${50 / WF_MAX_HZ * 100}%"><span>TX ${off}</span></div>`;
  } else {
    const bw = parseInt(S.settings.ardop_bw || '2000') || 2000;
    html = `<div class="wfband" style="left:${(1500 - bw / 2) / WF_MAX_HZ * 100}%;width:${bw / WF_MAX_HZ * 100}%"><span>ARDOP ${bw} Hz</span></div>`;
  }
  s.marks.innerHTML = html;
}
async function pollVfo() {
  try { renderVfo(await (await fetch('/api/vfo')).json()); } catch (e) { }
}
setInterval(() => {
  const t = $('#tabs button.active')?.dataset.tab;
  if (t === 'winlink' || t === 'js8') pollVfo();
}, 1000);

const WF = {
  ctx: null, stream: null, analyser: null, running: false, range: 40, floor: null, buf: null, lut: null, timer: null,
  deviceId: (() => { try { return localStorage.getItem('ares.wfdev') || ''; } catch (e) { return ''; } })(),
  makeLut() {
    const stops = [[0, [0, 0, 32]], [.25, [0, 40, 160]], [.5, [0, 190, 220]], [.7, [240, 230, 40]], [.85, [255, 120, 0]], [1, [255, 255, 255]]];
    this.lut = [];
    for (let i = 0; i < 256; i++) {
      const t = i / 255; let k = 0; while (k < stops.length - 2 && t > stops[k + 1][0]) k++;
      const [t0, c0] = stops[k], [t1, c1] = stops[k + 1]; const f = (t - t0) / (t1 - t0);
      this.lut.push(c0.map((c, j) => Math.round(c + (c1[j] - c) * f)));
    }
  },
  async start() {
    try {
      this.ctx = this.ctx || new AudioContext();
      await this.ctx.resume();
      this.stream = await navigator.mediaDevices.getUserMedia({ audio: { deviceId: this.deviceId ? { exact: this.deviceId } : undefined, echoCancellation: false, noiseSuppression: false, autoGainControl: false, channelCount: 1 } });
    } catch (e) { toast('Could not open audio input: ' + e.message, true); return; }
    this.source = this.ctx.createMediaStreamSource(this.stream);
    this.connect(this.source);
    this.running = true; this.ui(); this.listDevices();
    try { localStorage.setItem('ares.wfon', '1'); } catch (e) { }
  },
  connect(node) {
    if (!this.analyser) {
      this.analyser = this.ctx.createAnalyser();
      this.analyser.fftSize = 8192; this.analyser.smoothingTimeConstant = 0.2;
      this.analyser.minDecibels = -140; this.analyser.maxDecibels = 0;
      this.buf = new Float32Array(this.analyser.frequencyBinCount);
    }
    node.connect(this.analyser);
    if (!this.lut) this.makeLut();
    clearInterval(this.timer); this.timer = setInterval(() => this.row(), 110);
  },
  stop() {
    clearInterval(this.timer); this.running = false;
    if (this.stream) this.stream.getTracks().forEach(t => t.stop());
    if (this.source) this.source.disconnect();
    this.floor = null;
    this.stream = this.source = null; this.ui();
    try { localStorage.setItem('ares.wfon', '0'); } catch (e) { }
  },
  setDevice(id) {
    this.deviceId = id; try { localStorage.setItem('ares.wfdev', id); } catch (e) { }
    STRIPS.forEach(s => $('.wf-dev', s.el).value = id);
    if (this.running) { this.stop(); this.start(); }
  },
  async listDevices() {
    let devs = [];
    try { devs = (await navigator.mediaDevices.enumerateDevices()).filter(d => d.kind === 'audioinput'); } catch (e) { }
    const opts = '<option value="">Default input</option>' + devs.filter(d => d.deviceId && d.deviceId !== 'default').map((d, i) => `<option value="${esc(d.deviceId)}">${esc(d.label || 'Input ' + (i + 1))}</option>`).join('');
    STRIPS.forEach(s => { const sel = $('.wf-dev', s.el); sel.innerHTML = opts; sel.value = this.deviceId; });
  },
  ui() {
    STRIPS.forEach(s => {
      $('.wf-start', s.el).textContent = this.running ? 'Stop' : 'Start';
      $('.wfoff', s.el).classList.toggle('hidden', this.running);
    });
  },
  row() {
    const an = this.analyser; if (!an) return;
    const vis = STRIPS.filter(s => s.canvas.offsetParent !== null); if (!vis.length) return;
    an.getFloatFrequencyData(this.buf);
    const binHz = this.ctx.sampleRate / an.fftSize;
    const nb = Math.min(this.buf.length, Math.ceil(WF_MAX_HZ / binHz));
    // auto-level: track the noise floor (25th percentile) so the picture stays readable
    const sorted = Array.from(this.buf.subarray(0, nb)).filter(Number.isFinite).sort((a, b) => a - b);
    if (sorted.length) { const q = sorted[Math.floor(sorted.length * .25)]; this.floor = this.floor === null ? q : this.floor + (q - this.floor) * 0.1; }
    if (this.floor === null) return;
    const lo = this.floor - 3, span = this.range;
    for (const s of vis) {
      const cv = s.canvas, w = cv.clientWidth | 0;
      if (cv.width !== w) cv.width = w;
      const g = cv.getContext('2d'); const h = cv.height;
      g.drawImage(cv, 0, 0, w, h - 1, 0, 1, w, h - 1);
      const img = g.createImageData(w, 1); const d = img.data;
      for (let x = 0; x < w; x++) {
        const b0 = Math.floor(x / w * nb), b1 = Math.max(b0 + 1, Math.floor((x + 1) / w * nb));
        let m = -200; for (let b = b0; b < b1; b++) if (this.buf[b] > m) m = this.buf[b];
        const v = Math.max(0, Math.min(255, ((m - lo) / span) * 255 | 0)); const c = this.lut[v];
        d[x * 4] = c[0]; d[x * 4 + 1] = c[1]; d[x * 4 + 2] = c[2]; d[x * 4 + 3] = 255;
      }
      g.putImageData(img, 0, 0);
    }
  },
};
$$('.radiostrip').forEach(buildStrip);
WF.listDevices();
(async () => {  // resume the waterfall automatically if it was on and mic permission is already granted
  let on = '0'; try { on = localStorage.getItem('ares.wfon'); } catch (e) { }
  if (on !== '1') return;
  try { const p = await navigator.permissions.query({ name: 'microphone' }); if (p.state === 'granted') WF.start(); } catch (e) { }
})();

/* ---------------------------------------------------------------- JS8Call launcher */
async function js8AppState() {
  let st; try { st = await (await fetch('/api/js8/app')).json(); } catch (e) { return; }
  const b = $('#btnJs8Launch'), t = $('#js8AppState');
  if (st.running && st.connected) { b.textContent = 'JS8Call running'; b.disabled = true; b.classList.remove('primary'); t.textContent = ''; }
  else if (st.running) { b.textContent = 'Reconnect'; b.disabled = false; b.classList.remove('primary');
    t.textContent = st.enabled ? 'JS8Call is open; waiting for its TCP API (Settings › Reporting › TCP Server API, port ' + (S.settings.js8_port || 2442) + ')' : 'JS8Call is open, but JS8 is turned off in ARES Console settings'; }
  else { b.textContent = 'Start JS8Call'; b.disabled = false; b.classList.add('primary'); t.textContent = ''; }
}
$('#btnJs8Launch').onclick = async () => {
  const b = $('#btnJs8Launch'); b.disabled = true; b.textContent = 'Starting…';
  try {
    const r = await post('/api/js8/launch');
    toast(r.already_running ? 'JS8Call is already running; reconnecting' : 'Starting JS8Call…' + (r.enabled_now ? ' (JS8 turned on in Settings)' : ''));
  } catch (e) { }
  setTimeout(js8AppState, 1500);
};
setInterval(() => { if ($('#tabs button.active')?.dataset.tab === 'js8') js8AppState(); }, 3000);
js8AppState();

/* ---------------------------------------------------------------- rigctld / ARDOP launchers */
const HELPER_NAMES = { rigctld: 'rigctld', ardop: 'ARDOP' };
async function helperState() {
  let st; try { st = await (await fetch('/api/helpers')).json(); } catch (e) { return; }
  $$('.helper').forEach(el => {
    const k = el.dataset.helper, s = st[k], b = el.querySelector('button'), d = el.querySelector('.dot');
    if (!s || b.dataset.busy) return;
    d.className = 'dot ' + (s.running ? 'on' : 'off');
    el.title = s.command ? 'Command: ' + s.command + (s.log ? '\n\nLast output:\n' + s.log : '') : 'No command set (Settings)';
    if (s.running && s.started_here) { b.textContent = 'Stop ' + HELPER_NAMES[k]; b.disabled = false; b.classList.remove('primary'); b.dataset.act = 'stop'; }
    else if (s.running) { b.textContent = HELPER_NAMES[k] + ' running'; b.disabled = true; b.classList.remove('primary'); b.dataset.act = ''; }
    else { b.textContent = 'Start ' + HELPER_NAMES[k]; b.disabled = !s.local; b.classList.add('primary'); b.dataset.act = 'start'; }
  });
  $('#helperHint').textContent = (st.rigctld && !st.rigctld.running && !st.rigctld.command) ? 'Set the rigctld command in Settings › Radio' : '';
}
$$('.helper button').forEach(b => b.onclick = async () => {
  const k = b.closest('.helper').dataset.helper, act = b.dataset.act;
  if (!act) return;
  if (act === 'stop' && !confirm('Stop ' + HELPER_NAMES[k] + '?')) return;
  b.disabled = true; b.dataset.busy = '1'; b.textContent = act === 'start' ? 'Starting…' : 'Stopping…';
  try {
    const r = await post('/api/helpers/' + k + '/' + act);
    toast(act === 'stop' ? HELPER_NAMES[k] + ' stopped' : r.already_running ? HELPER_NAMES[k] + ' is already running' : HELPER_NAMES[k] + ' started' + (r.enabled_now ? ' (radio control turned on in Settings)' : ''));
  } catch (e) { }
  delete b.dataset.busy; helperState();
});
setInterval(() => { if ($('#tabs button.active')?.dataset.tab === 'winlink') helperState(); }, 3000);
helperState();

/* ---------------------------------------------------------------- about / quit */
fetch('/api/version').then(r => r.json()).then(v => { $('#aboutInfo').innerHTML = `ARES Console ${esc(v.version)} · data folder: <code>${esc(v.data_dir)}</code> · <a href="https://github.com/scottws70/ARES-Console" target="_blank" rel="noopener">github.com/scottws70/ARES-Console</a>`; }).catch(() => { });
$('#btnQuit').onclick = async () => {
  if (!confirm('Quit ARES Console? Radio, APRS and Winlink connections will stop until you start it again.')) return;
  await post('/api/shutdown');
  document.body.innerHTML = '<div style="padding:40px;font-family:sans-serif"><h2>ARES Console has stopped.</h2><p>Start it again from your applications menu. You can close this tab.</p></div>';
};
