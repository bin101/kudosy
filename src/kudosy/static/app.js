// ──────────────────────────────────────────────────────────────────────────────
// Kudosy UI — app.js
// ──────────────────────────────────────────────────────────────────────────────

// ── Helpers ───────────────────────────────────────────────────────────────────

const $ = id => document.getElementById(id);

function toast(msg, type = 'success') {
  const el = document.createElement('div');
  el.className = `toast toast-${type}`;
  const icon = type === 'success' ? '✓' : type === 'error' ? '✕' : 'ℹ';
  el.innerHTML = `<span>${icon}</span><span>${msg}</span>`;
  $('toast-container').appendChild(el);
  setTimeout(() => {
    el.classList.add('fade-out');
    setTimeout(() => el.remove(), 300);
  }, 3500);
}

async function fetchJson(url, opts = {}) {
  const res = await fetch(url, opts);
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || body.error || `HTTP ${res.status}`);
  }
  return res.json();
}

async function putJson(url, data) {
  return fetchJson(url, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
}

function formatRelative(isoString) {
  if (!isoString) return '—';
  const d = new Date(isoString);
  const diff = Date.now() - d.getTime();
  if (diff < 0) {
    const s = Math.round(-diff / 1000);
    if (s < 60) return `in ${s}s`;
    const m = Math.round(s / 60);
    if (m < 60) return `in ${m} min`;
    return `in ${Math.round(m / 60)} h`;
  }
  const s = Math.round(diff / 1000);
  if (s < 60) return `vor ${s}s`;
  const m = Math.round(s / 60);
  if (m < 60) return `vor ${m} min`;
  const h = Math.round(m / 60);
  if (h < 24) return `vor ${h} h`;
  return d.toLocaleDateString('de-DE');
}

function formatTime(isoString) {
  if (!isoString) return '—';
  return new Date(isoString).toLocaleTimeString('de-DE', { hour: '2-digit', minute: '2-digit' });
}

// "MountainBikeRide" → "Mountain Bike Ride"
function formatSportLabel(type) {
  return type.replace(/([A-Z])/g, ' $1').trim();
}

// ── State ─────────────────────────────────────────────────────────────────────

let sportTypes    = [];
let athleteLabels = {};
let pollTimer     = null;

// ── Tabs ──────────────────────────────────────────────────────────────────────

function initTabs() {
  document.querySelectorAll('.tab').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
      document.querySelectorAll('.tab-pane').forEach(p => p.classList.remove('active'));
      btn.classList.add('active');
      const pane = $(`tab-${btn.dataset.tab}`);
      if (pane) pane.classList.add('active');
      if (btn.dataset.tab === 'log') startPolling();
      else if (btn.dataset.tab === 'feed') { stopPolling(); pollStatus(); loadFeed(); }
      else { stopPolling(); pollStatus(); }
    });
  });
}

// ── Sport type <select> ───────────────────────────────────────────────────────

function buildSportTypeSelect(selectedType = '') {
  const sel = document.createElement('select');
  sel.className = 'sport-type-select';

  const blank = document.createElement('option');
  blank.value = '';
  blank.textContent = '— Sportart wählen —';
  if (!selectedType) blank.selected = true;
  sel.appendChild(blank);

  let found = !selectedType;
  for (const type of sportTypes) {
    const opt = document.createElement('option');
    opt.value = type;
    opt.textContent = formatSportLabel(type);
    if (type === selectedType) { opt.selected = true; found = true; }
    sel.appendChild(opt);
  }

  if (!found && selectedType) {
    const opt = document.createElement('option');
    opt.value = selectedType;
    opt.textContent = `${formatSportLabel(selectedType)} ↑`;
    opt.selected = true;
    sel.insertBefore(opt, sel.children[1]);
  }

  return sel;
}

// ── Rules table helpers ───────────────────────────────────────────────────────

function makeRemoveBtn(onClick) {
  const btn = document.createElement('button');
  btn.type = 'button';
  btn.className = 'btn-remove';
  btn.title = 'Entfernen';
  btn.textContent = '×';
  btn.addEventListener('click', onClick);
  return btn;
}

function addRuleRow(tbody, sportType = '', value = '') {
  const tr = document.createElement('tr');

  const tdType = document.createElement('td');
  tdType.appendChild(buildSportTypeSelect(sportType));

  const tdVal = document.createElement('td');
  const numInput = document.createElement('input');
  numInput.type = 'number';
  numInput.value = value !== '' ? value : '';
  numInput.min = '0';
  numInput.step = '0.1';
  numInput.placeholder = '—';
  numInput.style.maxWidth = '90px';
  tdVal.appendChild(numInput);

  const tdRemove = document.createElement('td');
  tdRemove.appendChild(makeRemoveBtn(() => tr.remove()));

  tr.appendChild(tdType);
  tr.appendChild(tdVal);
  tr.appendChild(tdRemove);
  tbody.appendChild(tr);
}

function getRulesFromTable(tbody) {
  const result = {};
  tbody.querySelectorAll('tr').forEach(tr => {
    const sel    = tr.querySelector('select');
    const numIn  = tr.querySelector('input[type="number"]');
    if (!sel || !numIn) return;
    const type = sel.value.trim();
    const raw  = numIn.value.trim();
    if (type && raw !== '') {
      const val = parseFloat(raw);
      if (!isNaN(val)) result[type] = val;
    }
  });
  return result;
}

function populateRulesTable(tbody, rules) {
  tbody.innerHTML = '';
  for (const [type, val] of Object.entries(rules || {})) {
    addRuleRow(tbody, type, val);
  }
}

// ── Athlete list helpers ──────────────────────────────────────────────────────

async function doAthleteNameLookup(id, nameEl, lookupBtn) {
  if (!id) { toast('Bitte zuerst eine Athlete ID eingeben', 'info'); return; }
  const prev = lookupBtn.textContent;
  lookupBtn.disabled = true;
  lookupBtn.textContent = '…';
  nameEl.textContent = '…';
  nameEl.className = 'athlete-name muted';
  try {
    const r = await fetchJson(`/api/athletes/${id}`);
    if (r.name) {
      athleteLabels[id] = r.name;
      nameEl.textContent = r.name;
      nameEl.className = 'athlete-name';
    } else {
      nameEl.textContent = 'nicht gefunden';
    }
  } catch {
    nameEl.textContent = 'Fehler';
  } finally {
    lookupBtn.disabled = false;
    lookupBtn.textContent = prev;
  }
}

function addAthleteRow(listEl, id = '') {
  const li = document.createElement('li');
  li.className = 'athlete-row';

  const idInput = document.createElement('input');
  idInput.type = 'text';
  idInput.value = id;
  idInput.placeholder = 'Athlete ID';
  idInput.className = 'athlete-id';
  idInput.inputMode = 'numeric';

  const nameEl = document.createElement('span');
  const cachedName = id ? athleteLabels[id] : null;
  nameEl.className = 'athlete-name' + (cachedName ? '' : ' muted');
  nameEl.textContent = cachedName || (id ? '—' : '');

  const lookupBtn = document.createElement('button');
  lookupBtn.type = 'button';
  lookupBtn.className = 'btn-icon btn-lookup';
  lookupBtn.title = 'Name von Strava laden';
  lookupBtn.textContent = '🔍';
  lookupBtn.addEventListener('click', () =>
    doAthleteNameLookup(idInput.value.trim(), nameEl, lookupBtn));

  li.appendChild(idInput);
  li.appendChild(nameEl);
  li.appendChild(lookupBtn);
  li.appendChild(makeRemoveBtn(() => li.remove()));
  listEl.appendChild(li);

  if (!id) idInput.focus();
  return { li, idInput, nameEl, lookupBtn };
}

async function autoLookupMissingNames(listEl) {
  const rows = listEl.querySelectorAll('.athlete-row');
  const pending = [];
  rows.forEach(li => {
    const idInput   = li.querySelector('.athlete-id');
    const nameEl    = li.querySelector('.athlete-name');
    const lookupBtn = li.querySelector('.btn-lookup');
    const id = idInput?.value.trim();
    if (id && !athleteLabels[id]) {
      pending.push(doAthleteNameLookup(id, nameEl, lookupBtn));
    }
  });
  await Promise.allSettled(pending);
}

function getAthleteIds(listEl) {
  return Array.from(listEl.querySelectorAll('.athlete-id'))
    .map(i => i.value.trim())
    .filter(Boolean);
}

// ── Activity names list helpers ───────────────────────────────────────────────

function addListItem(listEl, value = '', placeholder = '') {
  const li = document.createElement('li');
  const input = document.createElement('input');
  input.type = 'text';
  input.value = value;
  input.placeholder = placeholder;
  li.appendChild(input);
  li.appendChild(makeRemoveBtn(() => li.remove()));
  listEl.appendChild(li);
  if (!value) input.focus();
}

function getListValues(listEl) {
  return Array.from(listEl.querySelectorAll('input'))
    .map(i => i.value.trim())
    .filter(Boolean);
}

// ── Config tab ────────────────────────────────────────────────────────────────

async function loadConfig() {
  const [cfg, labels] = await Promise.all([
    fetchJson('/api/config'),
    fetchJson('/api/athlete-labels').catch(() => ({})),
  ]);
  athleteLabels = labels;

  $('cookieInput').value    = cfg.stravaSessionCookie || '';
  $('athleteIdInput').value = cfg.athleteId || '';

  const ignoreList = $('ignore-list');
  ignoreList.innerHTML = '';
  for (const id of (cfg.ignoreAthletes || [])) {
    addAthleteRow(ignoreList, id);
  }
  autoLookupMissingNames(ignoreList);

  populateRulesTable($('tbody-distance'), cfg.kudoRules?.minDistance);
  populateRulesTable($('tbody-time'),     cfg.kudoRules?.minTime);

  const namesList = $('activity-names-list');
  namesList.innerHTML = '';
  for (const n of (cfg.kudoRules?.activityNames || [])) {
    addListItem(namesList, n, 'Regex-Muster, z.B. Morning.*');
  }
}

async function saveConfig(e) {
  e.preventDefault();
  try {
    const cfg = {
      stravaSessionCookie: $('cookieInput').value.trim(),
      athleteId:           $('athleteIdInput').value.trim(),
      ignoreAthletes:      getAthleteIds($('ignore-list')),
      kudoRules: {
        minDistance:   getRulesFromTable($('tbody-distance')),
        minTime:       getRulesFromTable($('tbody-time')),
        activityNames: getListValues($('activity-names-list')),
      },
    };
    if (!cfg.kudoRules.activityNames.length) delete cfg.kudoRules.activityNames;
    await putJson('/api/config', cfg);
    toast('Konfiguration gespeichert ✓');
  } catch (err) {
    toast(err.message, 'error');
  }
}

function initConfigTab() {
  $('form-config').addEventListener('submit', saveConfig);
  $('btn-add-athlete').addEventListener('click', () => addAthleteRow($('ignore-list'), ''));
  $('btn-add-distance').addEventListener('click', () => addRuleRow($('tbody-distance')));
  $('btn-add-time').addEventListener('click', () => addRuleRow($('tbody-time')));
  $('btn-add-name').addEventListener('click', () =>
    addListItem($('activity-names-list'), '', 'Regex-Muster, z.B. Morning.*'));
  $('btn-load-all-names')?.addEventListener('click', () =>
    autoLookupMissingNames($('ignore-list')));
}

// ── Defaults tab ──────────────────────────────────────────────────────────────

async function loadDefaults() {
  const d = await fetchJson('/api/defaults');
  $('catchAllDist').value = d.catchAll?.minDistance || 0;
  $('catchAllTime').value = d.catchAll?.minTime     || 0;
  populateRulesTable($('tbody-def-distance'), d.kudoRules?.minDistance);
  populateRulesTable($('tbody-def-time'),     d.kudoRules?.minTime);
}

async function saveDefaults(e) {
  e.preventDefault();
  try {
    const data = {
      catchAll: {
        minDistance: parseFloat($('catchAllDist').value) || 0,
        minTime:     parseFloat($('catchAllTime').value) || 0,
      },
      kudoRules: {
        minDistance:   getRulesFromTable($('tbody-def-distance')),
        minTime:       getRulesFromTable($('tbody-def-time')),
        activityNames: [],
      },
    };
    await putJson('/api/defaults', data);
    toast('Defaults gespeichert ✓');
  } catch (err) {
    toast(err.message, 'error');
  }
}

function initDefaultsTab() {
  $('form-defaults').addEventListener('submit', saveDefaults);
  $('btn-add-def-distance').addEventListener('click', () => addRuleRow($('tbody-def-distance')));
  $('btn-add-def-time').addEventListener('click', () => addRuleRow($('tbody-def-time')));
}

// ── Settings tab ──────────────────────────────────────────────────────────────

async function loadSettings() {
  const s = await fetchJson('/api/settings');
  $('schedulerEnabled').checked     = s.schedulerEnabled;
  $('intervalMinutes').value         = s.intervalMinutes ?? 60;
  $('jitterMinutes').value           = s.jitterMinutes   ?? 15;
  $('globalDryRun').checked          = s.dryRun;
  $('minKudosDelaySeconds').value    = s.minKudosDelaySeconds ?? 3;
  $('maxKudosDelaySeconds').value    = s.maxKudosDelaySeconds ?? 25;
  $('shuffleOrder').checked          = s.shuffleOrder ?? true;
  toggleIntervalVisibility(s.schedulerEnabled);
}

function toggleIntervalVisibility(enabled) {
  const opacity = enabled ? '1' : '0.4';
  $('interval-group').style.opacity = opacity;
  $('jitter-group').style.opacity   = opacity;
  $('intervalMinutes').disabled     = !enabled;
  $('jitterMinutes').disabled       = !enabled;
}

async function saveSettings(e) {
  e.preventDefault();
  try {
    const data = {
      schedulerEnabled:      $('schedulerEnabled').checked,
      intervalMinutes:       Math.max(5, parseInt($('intervalMinutes').value) || 60),
      jitterMinutes:         Math.max(0, parseFloat($('jitterMinutes').value) || 0),
      dryRun:                $('globalDryRun').checked,
      minKudosDelaySeconds:  Math.max(0, parseFloat($('minKudosDelaySeconds').value) || 0),
      maxKudosDelaySeconds:  Math.max(0, parseFloat($('maxKudosDelaySeconds').value) || 0),
      shuffleOrder:          $('shuffleOrder').checked,
    };
    await putJson('/api/settings', data);
    toast('Einstellungen gespeichert ✓');
    pollStatus();
  } catch (err) {
    toast(err.message, 'error');
  }
}

function initSettingsTab() {
  $('form-settings').addEventListener('submit', saveSettings);
  $('schedulerEnabled').addEventListener('change', e =>
    toggleIntervalVisibility(e.target.checked));
}

// ── Status & log polling ──────────────────────────────────────────────────────

async function pollStatus() {
  try {
    const s = await fetchJson('/api/status');
    const badge = $('status-badge');
    if (s.running) {
      badge.className = 'badge badge-running';
      badge.textContent = 'Läuft…';
    } else if (s.lastRun?.success === false) {
      badge.className = 'badge badge-error';
      badge.textContent = 'Fehler';
    } else if (s.lastRun?.success === true) {
      badge.className = 'badge badge-ok';
      badge.textContent = s.lastRun.dry_run ? 'Dry-Run OK' : 'OK';
    } else {
      badge.className = 'badge badge-idle';
      badge.textContent = 'Bereit';
    }

    $('btn-run').disabled     = s.running;
    $('btn-dry-run').disabled = s.running;

    if (s.lastRun) {
      const lr = s.lastRun;
      const success = lr.success ? (lr.dry_run ? '🔍 Dry-Run' : '✅ OK') : '❌ Fehler';
      $('val-last-run').textContent = `${success}  ${formatRelative(lr.finished_at)}`;
      $('val-last-run').style.color = lr.success ? '' : 'var(--error)';
      const kudosCount = lr.dry_run ? lr.would_give : lr.given;
      $('val-kudos').textContent = `${kudosCount} Kudos ${lr.dry_run ? '(simuliert)' : 'gesendet'}`;
    } else {
      $('val-last-run').textContent = 'Noch kein Lauf';
      $('val-kudos').textContent    = '—';
    }

    if (s.schedulerEnabled && s.nextRunAt) {
      $('val-next-run').textContent = formatRelative(s.nextRunAt);
      $('val-interval').textContent = `alle ${s.intervalMinutes} min · ${formatTime(s.nextRunAt)} Uhr`;
    } else {
      $('val-next-run').textContent = 'Deaktiviert';
      $('val-interval').textContent = 'Scheduler ist aus';
    }

    // Update footer version
    const versionEl = $('footer-version');
    if (versionEl && s.version) versionEl.textContent = `Kudosy v${s.version}`;
  } catch { /* ignore polling errors */ }
}

async function pollLog() {
  try {
    const text = await fetch('/api/log').then(r => r.text());
    const el   = $('log-output');
    const atBottom = el.scrollHeight - el.clientHeight <= el.scrollTop + 10;
    el.textContent = text;
    if (atBottom) el.scrollTop = el.scrollHeight;
  } catch { /* ignore */ }
  await pollStatus();
}

function startPolling() {
  stopPolling();
  pollLog();
  pollTimer = setInterval(() => {
    if ($('auto-refresh').checked) pollLog();
    else pollStatus();
  }, 3000);
}

function stopPolling() {
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
}

// ── Feed tab ──────────────────────────────────────────────────────────────────

const FEED_REASON_LABELS = {
  already:    'bereits geliked',
  ignore:     'Athlet ignoriert',
  criteria:   'unter Schwellenwert',
  name_match: 'Name-Treffer',
  default:    'Standard',
};

async function loadFeed() {
  const container = $('feed-list');
  if (!container) return;
  container.innerHTML = '<p class="hint">Lade Feed…</p>';
  try {
    const activities = await fetchJson('/api/feed');
    if (!activities.length) {
      container.innerHTML = '<p class="hint feed-empty">Keine Aktivitäten im Feed gefunden. Prüfe ob der Session-Cookie gültig ist und führe ggf. einen Dry-Run aus.</p>';
      return;
    }
    container.innerHTML = '';
    activities.forEach(act => {
      const card = document.createElement('div');
      card.className = 'feed-card';

      const reasonLabel = FEED_REASON_LABELS[act.reason] || act.reason;
      const decisionClass = act.give_kudos ? 'feed-decision-give' : 'feed-decision-skip';
      const decisionText  = act.give_kudos
        ? '→ würde Kudo geben'
        : `– übersprungen: ${reasonLabel}`;

      const kudosBadge = act.has_kudoed
        ? '<span class="feed-kudo-badge feed-kudo-done">✅ Kudo gegeben</span>'
        : '<span class="feed-kudo-badge feed-kudo-pending">○ noch kein Kudo</span>';

      const statsParts = Object.entries(act.stats)
        .map(([k, v]) => `<span class="feed-stat"><strong>${k}:</strong> ${v}</span>`)
        .join('');
      const statsHtml = statsParts ? `<div class="feed-stats">${statsParts}</div>` : '';
      const sportLabel = act.sport_type ? formatSportLabel(act.sport_type) : '—';

      card.innerHTML = `
        <div class="feed-card-header">
          <span class="feed-sport">${sportLabel}</span>
          ${kudosBadge}
        </div>
        <div class="feed-card-body">
          <div class="feed-activity-name">${act.activity_name || '(kein Name)'}</div>
          <div class="feed-athlete-name">${act.athlete_name}</div>
          ${statsHtml}
        </div>
        <div class="feed-card-footer">
          <span class="feed-decision ${decisionClass}">${decisionText}</span>
        </div>
      `;
      container.appendChild(card);
    });
  } catch (err) {
    const is401 = err.message && (err.message.includes('401') || err.message.toLowerCase().includes('cookie'));
    container.innerHTML = is401
      ? '<p class="hint feed-error">⚠️ Session-Cookie ungültig oder abgelaufen. Bitte neuen Cookie in der Konfiguration eintragen.</p>'
      : `<p class="hint feed-error">Fehler beim Laden des Feeds: ${err.message}</p>`;
  }
}

function initFeedTab() {
  const btn = $('btn-refresh-feed');
  if (btn) btn.addEventListener('click', loadFeed);
}

// ── Run buttons ───────────────────────────────────────────────────────────────

function initRunButtons() {
  $('btn-run').addEventListener('click', async () => {
    try {
      await fetchJson('/api/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: '{}',
      });
      document.querySelector('.tab[data-tab="log"]').click();
    } catch (err) {
      toast(err.message, 'error');
    }
  });

  $('btn-dry-run').addEventListener('click', async () => {
    try {
      await fetch('/api/run?dryRun=1', { method: 'POST' });
      document.querySelector('.tab[data-tab="log"]').click();
    } catch (err) {
      toast(err.message, 'error');
    }
  });
}

// ── Password reveal ───────────────────────────────────────────────────────────

function initRevealButtons() {
  document.querySelectorAll('[data-reveal]').forEach(btn => {
    btn.addEventListener('click', () => {
      const input = $(btn.dataset.reveal);
      if (!input) return;
      const hidden = input.type === 'password';
      input.type = hidden ? 'text' : 'password';
      btn.textContent = hidden ? '🙈' : '👁';
    });
  });
}

// ── Init ──────────────────────────────────────────────────────────────────────

async function init() {
  try {
    sportTypes = await fetchJson('/api/sport-types');
  } catch {
    sportTypes = [];
  }

  initTabs();
  initConfigTab();
  initDefaultsTab();
  initSettingsTab();
  initFeedTab();
  initRunButtons();
  initRevealButtons();

  await Promise.allSettled([
    loadConfig().catch(err => toast('Config nicht geladen: ' + err.message, 'error')),
    loadDefaults().catch(err => toast('Defaults nicht geladen: ' + err.message, 'error')),
    loadSettings().catch(err => toast('Einstellungen nicht geladen: ' + err.message, 'error')),
  ]);

  await pollStatus();
  setInterval(pollStatus, 10000);
}

init().catch(err => console.error('[init]', err));
