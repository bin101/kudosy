// ──────────────────────────────────────────────────────────────────────────────
// Kudosy UI — app.js
// ──────────────────────────────────────────────────────────────────────────────

import {
  SUPPORTED,
  LANG_LABELS,
  t,
  getLang,
  currentLang,
  localeFor,
  setLang,
  applyStaticTranslations,
} from './i18n.js';

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
    // detail may be a structured {code, message} object or a plain string
    const detail = body.detail;
    if (detail && typeof detail === 'object' && detail.code) {
      const key = `error.${detail.code}`;
      const translated = t(key);
      // if key not found, fall back to the message field
      throw new Error(translated !== key ? translated : (detail.message || `HTTP ${res.status}`));
    }
    throw new Error(
      (typeof detail === 'string' ? detail : null) || body.error || `HTTP ${res.status}`
    );
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
    if (s < 60) return t('time.inSeconds', { n: s });
    const m = Math.round(s / 60);
    if (m < 60) return t('time.inMinutes', { n: m });
    return t('time.inHours', { n: Math.round(m / 60) });
  }
  const s = Math.round(diff / 1000);
  if (s < 60) return t('time.agoSeconds', { n: s });
  const m = Math.round(s / 60);
  if (m < 60) return t('time.agoMinutes', { n: m });
  const h = Math.round(m / 60);
  if (h < 24) return t('time.agoHours', { n: h });
  return d.toLocaleDateString(localeFor(currentLang()));
}

function formatTime(isoString) {
  if (!isoString) return '—';
  return new Date(isoString).toLocaleTimeString(localeFor(currentLang()), {
    hour: '2-digit',
    minute: '2-digit',
  });
}

// "MountainBikeRide" → "Mountain Bike Ride"
function formatSportLabel(type) {
  return type.replace(/([A-Z])/g, ' $1').trim();
}

// ── State ─────────────────────────────────────────────────────────────────────

let sportTypes    = [];
let athleteLabels = {};
let pollTimer     = null;

// ── Language selector ─────────────────────────────────────────────────────────

function initLangSelect() {
  const sel = $('lang-select');
  if (!sel) return;
  for (const lang of SUPPORTED) {
    const opt = document.createElement('option');
    opt.value = lang;
    opt.textContent = LANG_LABELS[lang];
    if (lang === getLang()) opt.selected = true;
    sel.appendChild(opt);
  }
  sel.addEventListener('change', () => {
    setLang(sel.value, () => {
      // Re-render dynamic areas after language change
      pollStatus();
      const activeFeedPane = document.querySelector('#tab-feed.active');
      if (activeFeedPane) loadFeed();
    });
    // Keep select in sync (applyStaticTranslations won't touch it)
    sel.value = sel.value;
  });
}

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
  blank.textContent = t('table.sportType.placeholder');
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
  btn.title = t('table.removeBtn.title');
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

// ── Athlete management list helpers ──────────────────────────────────────────
// Each athlete row has: name/id display, Allow/Deny switch, remove button.
// The switch state determines which list (allowAthletes / ignoreAthletes) the ID goes into.

/**
 * Add an athlete to the unified management list.
 * @param {HTMLElement} listEl - the <ul> element
 * @param {string} id         - athlete ID
 * @param {string} name       - display name (from cache or search)
 * @param {string} mode       - 'allow' | 'deny' (default 'deny')
 */
function addAthleteManagedRow(listEl, id = '', name = '', mode = 'deny') {
  const li = document.createElement('li');
  li.className = 'athlete-manage-row';
  li.dataset.athleteId = id;

  const displayName = name || (id ? (athleteLabels[id] || id) : '');

  // Avatar placeholder (shown as initials circle when no avatarUrl)
  const avatar = document.createElement('span');
  avatar.className = 'athlete-avatar';
  avatar.textContent = displayName ? displayName[0].toUpperCase() : '?';

  const info = document.createElement('span');
  info.className = 'athlete-info';
  const nameSpan = document.createElement('strong');
  nameSpan.className = 'athlete-info-name';
  nameSpan.textContent = displayName || id;
  const idSpan = document.createElement('small');
  idSpan.className = 'athlete-info-id';
  idSpan.textContent = `ID: ${id}`;
  info.appendChild(nameSpan);
  info.appendChild(idSpan);

  // Allow / Deny switch
  const switchLabel = document.createElement('label');
  switchLabel.className = 'athlete-switch';

  const allowBtn = document.createElement('button');
  allowBtn.type = 'button';
  allowBtn.className = 'athlete-switch-btn athlete-switch-allow' + (mode === 'allow' ? ' active' : '');
  allowBtn.textContent = t('config.athletes.allow');

  const denyBtn = document.createElement('button');
  denyBtn.type = 'button';
  denyBtn.className = 'athlete-switch-btn athlete-switch-deny' + (mode === 'deny' ? ' active' : '');
  denyBtn.textContent = t('config.athletes.deny');

  allowBtn.addEventListener('click', () => {
    allowBtn.classList.add('active');
    denyBtn.classList.remove('active');
    li.dataset.mode = 'allow';
  });
  denyBtn.addEventListener('click', () => {
    denyBtn.classList.add('active');
    allowBtn.classList.remove('active');
    li.dataset.mode = 'deny';
  });

  li.dataset.mode = mode;
  switchLabel.appendChild(allowBtn);
  switchLabel.appendChild(denyBtn);

  li.appendChild(avatar);
  li.appendChild(info);
  li.appendChild(switchLabel);
  li.appendChild(makeRemoveBtn(() => li.remove()));
  listEl.appendChild(li);
  return li;
}

/**
 * Get the allow/deny lists from the athlete management list.
 * Returns { allowAthletes: string[], ignoreAthletes: string[] }
 */
function getAthleteLists(listEl) {
  const allowAthletes = [];
  const ignoreAthletes = [];
  listEl.querySelectorAll('.athlete-manage-row').forEach(li => {
    const id = li.dataset.athleteId;
    if (!id) return;
    if (li.dataset.mode === 'allow') {
      allowAthletes.push(id);
    } else {
      ignoreAthletes.push(id);
    }
  });
  return { allowAthletes, ignoreAthletes };
}

async function autoLookupMissingNames(listEl) {
  // No-op for the new managed list (names come from search); kept for compatibility
  // with btn-load-all-names which re-fetches all labels from Strava.
}

// ── Athlete search modal ──────────────────────────────────────────────────────

let _athleteSearchDebounceTimer = null;

function openAthleteSearchModal() {
  const modal = $('athlete-search-modal');
  if (!modal) return;
  modal.hidden = false;
  const input = $('athlete-search-input');
  if (input) { input.value = ''; input.focus(); }
  const results = $('athlete-search-results');
  if (results) results.innerHTML = `<p class="hint">${t('config.athletes.search.hint')}</p>`;
}

function closeAthleteSearchModal() {
  const modal = $('athlete-search-modal');
  if (modal) modal.hidden = true;
  clearTimeout(_athleteSearchDebounceTimer);
}

async function performAthleteSearch(query) {
  const results = $('athlete-search-results');
  if (!results) return;
  if (!query || query.length < 2) {
    results.innerHTML = `<p class="hint">${t('config.athletes.search.hint')}</p>`;
    return;
  }
  results.innerHTML = `<p class="hint">${t('config.athletes.search.searching')}</p>`;
  try {
    const athletes = await fetchJson(`/api/athletes/search?q=${encodeURIComponent(query)}`);
    if (!athletes.length) {
      results.innerHTML = `<p class="hint">${t('config.athletes.search.noResults')}</p>`;
      return;
    }
    results.innerHTML = '';
    athletes.forEach(athlete => {
      const item = document.createElement('div');
      item.className = 'athlete-search-item';

      const avatar = document.createElement('span');
      avatar.className = 'athlete-avatar';
      if (athlete.avatarUrl) {
        const img = document.createElement('img');
        img.src = athlete.avatarUrl;
        img.alt = athlete.name;
        img.onerror = () => { avatar.textContent = athlete.name[0]?.toUpperCase() || '?'; };
        avatar.appendChild(img);
      } else {
        avatar.textContent = athlete.name[0]?.toUpperCase() || '?';
      }

      const info = document.createElement('span');
      info.className = 'athlete-search-item-info';
      const nameEl = document.createElement('strong');
      nameEl.textContent = athlete.name;
      const idEl = document.createElement('small');
      idEl.textContent = `ID: ${athlete.id}`;
      info.appendChild(nameEl);
      info.appendChild(idEl);

      item.appendChild(avatar);
      item.appendChild(info);
      item.addEventListener('click', () => {
        athleteLabels[athlete.id] = athlete.name;
        addAthleteManagedRow($('athlete-manage-list'), athlete.id, athlete.name, 'deny');
        closeAthleteSearchModal();
      });
      results.appendChild(item);
    });
  } catch {
    results.innerHTML = `<p class="hint feed-error">${t('config.athletes.search.error')}</p>`;
  }
}

function initAthleteSearchModal() {
  const closeBtn = $('btn-close-athlete-modal');
  if (closeBtn) closeBtn.addEventListener('click', closeAthleteSearchModal);

  const overlay = $('athlete-search-modal');
  if (overlay) {
    overlay.addEventListener('click', e => {
      if (e.target === overlay) closeAthleteSearchModal();
    });
  }

  const input = $('athlete-search-input');
  if (input) {
    input.addEventListener('input', e => {
      clearTimeout(_athleteSearchDebounceTimer);
      const q = e.target.value.trim();
      _athleteSearchDebounceTimer = setTimeout(() => performAthleteSearch(q), 350);
    });
  }

  document.addEventListener('keydown', e => {
    if (e.key === 'Escape') closeAthleteSearchModal();
  });
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

  // Unified athlete management list: merge ignoreAthletes + allowAthletes
  const manageList = $('athlete-manage-list');
  manageList.innerHTML = '';
  for (const id of (cfg.ignoreAthletes || [])) {
    addAthleteManagedRow(manageList, id, athleteLabels[id] || '', 'deny');
  }
  for (const id of (cfg.allowAthletes || [])) {
    addAthleteManagedRow(manageList, id, athleteLabels[id] || '', 'allow');
  }

  populateRulesTable($('tbody-distance'), cfg.kudoRules?.minDistance);
  populateRulesTable($('tbody-time'),     cfg.kudoRules?.minTime);

  const namesList = $('activity-names-list');
  namesList.innerHTML = '';
  for (const n of (cfg.kudoRules?.activityNames || [])) {
    addListItem(namesList, n, t('config.activityNames.placeholder'));
  }
}

async function saveConfig(e) {
  e.preventDefault();
  try {
    const { allowAthletes, ignoreAthletes } = getAthleteLists($('athlete-manage-list'));
    const cfg = {
      stravaSessionCookie: $('cookieInput').value.trim(),
      athleteId:           $('athleteIdInput').value.trim(),
      ignoreAthletes,
      allowAthletes,
      kudoRules: {
        minDistance:   getRulesFromTable($('tbody-distance')),
        minTime:       getRulesFromTable($('tbody-time')),
        activityNames: getListValues($('activity-names-list')),
      },
    };
    if (!cfg.kudoRules.activityNames.length) delete cfg.kudoRules.activityNames;
    await putJson('/api/config', cfg);
    toast(t('toast.config.saved'));
  } catch (err) {
    toast(err.message, 'error');
  }
}

function initConfigTab() {
  $('form-config').addEventListener('submit', saveConfig);
  $('btn-add-athlete').addEventListener('click', openAthleteSearchModal);
  $('btn-add-distance').addEventListener('click', () => addRuleRow($('tbody-distance')));
  $('btn-add-time').addEventListener('click', () => addRuleRow($('tbody-time')));
  $('btn-add-name').addEventListener('click', () =>
    addListItem($('activity-names-list'), '', t('config.activityNames.placeholder')));
  // "Load all names" now just caches labels from the API; for managed list just refresh labels
  $('btn-load-all-names')?.addEventListener('click', async () => {
    try {
      const labels = await fetchJson('/api/athlete-labels');
      athleteLabels = { ...athleteLabels, ...labels };
      // Refresh displayed names in the managed list
      $('athlete-manage-list').querySelectorAll('.athlete-manage-row').forEach(li => {
        const id = li.dataset.athleteId;
        if (id && labels[id]) {
          const nameEl = li.querySelector('.athlete-info-name');
          if (nameEl) nameEl.textContent = labels[id];
        }
      });
    } catch {
      toast(t('toast.config.loadError', { msg: '' }), 'error');
    }
  });
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
    toast(t('toast.defaults.saved'));
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

// ── Schedule matrix helpers ───────────────────────────────────────────────────

/** Render the 7×24 schedule matrix into #schedule-matrix. */
function renderScheduleMatrix(matrix) {
  const container = $('schedule-matrix');
  if (!container) return;
  container.innerHTML = '';

  const days = t('settings.schedule.days') || ['Mo', 'Di', 'Mi', 'Do', 'Fr', 'Sa', 'So'];

  // Header row: corner + hours 0–23
  const headerRow = document.createElement('div');
  headerRow.className = 'schedule-row schedule-header';
  const corner = document.createElement('div');
  corner.className = 'schedule-cell schedule-corner';
  headerRow.appendChild(corner);
  for (let h = 0; h < 24; h++) {
    const cell = document.createElement('div');
    cell.className = 'schedule-cell schedule-hour-label';
    cell.textContent = h;
    cell.dataset.col = h;
    cell.title = `Toggle hour ${h} (all days)`;
    cell.addEventListener('click', () => toggleScheduleColumn(h));
    headerRow.appendChild(cell);
  }
  container.appendChild(headerRow);

  // Day rows
  for (let d = 0; d < 7; d++) {
    const row = document.createElement('div');
    row.className = 'schedule-row';

    const dayLabel = document.createElement('div');
    dayLabel.className = 'schedule-cell schedule-day-label';
    dayLabel.textContent = days[d] || d;
    dayLabel.dataset.row = d;
    dayLabel.title = `Toggle ${days[d] || d} (all hours)`;
    dayLabel.addEventListener('click', () => toggleScheduleRow(d));
    row.appendChild(dayLabel);

    for (let h = 0; h < 24; h++) {
      const cell = document.createElement('div');
      const allowed = matrix[d]?.[h] !== false; // undefined → allowed
      cell.className = 'schedule-cell schedule-slot' + (allowed ? ' allowed' : '');
      cell.dataset.row = d;
      cell.dataset.col = h;
      cell.addEventListener('click', () => {
        cell.classList.toggle('allowed');
      });
      row.appendChild(cell);
    }
    container.appendChild(row);
  }
}

function toggleScheduleRow(rowIdx) {
  const slots = document.querySelectorAll(`#schedule-matrix .schedule-slot[data-row="${rowIdx}"]`);
  const anyOff = Array.from(slots).some(c => !c.classList.contains('allowed'));
  slots.forEach(c => c.classList.toggle('allowed', anyOff));
}

function toggleScheduleColumn(colIdx) {
  const slots = document.querySelectorAll(`#schedule-matrix .schedule-slot[data-col="${colIdx}"]`);
  const anyOff = Array.from(slots).some(c => !c.classList.contains('allowed'));
  slots.forEach(c => c.classList.toggle('allowed', anyOff));
}

function getScheduleMatrix() {
  const matrix = [];
  for (let d = 0; d < 7; d++) {
    const row = [];
    for (let h = 0; h < 24; h++) {
      const cell = document.querySelector(`#schedule-matrix .schedule-slot[data-row="${d}"][data-col="${h}"]`);
      row.push(cell ? cell.classList.contains('allowed') : true);
    }
    matrix.push(row);
  }
  return matrix;
}

function toggleScheduleMatrixEnabled(enabled) {
  const wrap = $('schedule-matrix-wrap');
  const tzGroup = $('timezone-group');
  if (wrap) wrap.style.opacity = enabled ? '1' : '0.4';
  if (wrap) wrap.style.pointerEvents = enabled ? '' : 'none';
  if (tzGroup) tzGroup.style.opacity = enabled ? '1' : '0.4';
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
  $('kudosScheduleEnabled').checked  = s.kudosScheduleEnabled ?? false;
  $('timezone').value                = s.timezone ?? 'Europe/Berlin';
  toggleIntervalVisibility(s.schedulerEnabled);
  toggleScheduleMatrixEnabled(s.kudosScheduleEnabled ?? false);

  // Render the schedule matrix (all-true by default)
  const matrix = s.kudosScheduleMatrix || Array.from({ length: 7 }, () => Array(24).fill(true));
  renderScheduleMatrix(matrix);
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
      kudosScheduleEnabled:  $('kudosScheduleEnabled').checked,
      timezone:              $('timezone').value.trim() || 'Europe/Berlin',
      kudosScheduleMatrix:   getScheduleMatrix(),
    };
    await putJson('/api/settings', data);
    toast(t('toast.settings.saved'));
    pollStatus();
  } catch (err) {
    toast(err.message, 'error');
  }
}

function initSettingsTab() {
  $('form-settings').addEventListener('submit', saveSettings);
  $('schedulerEnabled').addEventListener('change', e =>
    toggleIntervalVisibility(e.target.checked));
  $('kudosScheduleEnabled').addEventListener('change', e =>
    toggleScheduleMatrixEnabled(e.target.checked));
}

// ── Status & log polling ──────────────────────────────────────────────────────

async function pollStatus() {
  try {
    const s = await fetchJson('/api/status');
    const badge = $('status-badge');
    if (s.running) {
      badge.className = 'badge badge-running';
      badge.textContent = t('status.running');
    } else if (s.lastRun?.success === false) {
      badge.className = 'badge badge-error';
      badge.textContent = t('status.error');
    } else if (s.lastRun?.success === true) {
      badge.className = 'badge badge-ok';
      badge.textContent = s.lastRun.dry_run ? t('status.dryRunOk') : t('status.ok');
    } else {
      badge.className = 'badge badge-idle';
      badge.textContent = t('status.ready');
    }

    $('btn-run').disabled     = s.running;
    $('btn-dry-run').disabled = s.running;

    if (s.lastRun) {
      const lr = s.lastRun;
      const successLabel = lr.success
        ? (lr.dry_run ? t('run.dryRun') : t('run.success'))
        : t('run.error');
      $('val-last-run').textContent = `${successLabel}  ${formatRelative(lr.finished_at)}`;
      $('val-last-run').style.color = lr.success ? '' : 'var(--error)';
      const kudosCount = lr.dry_run ? lr.would_give : lr.given;
      $('val-kudos').textContent = lr.dry_run
        ? t('status.kudosSimulated', { n: kudosCount })
        : t('status.kudosSent', { n: kudosCount });
    } else {
      $('val-last-run').textContent = t('status.noRun');
      $('val-kudos').textContent    = '—';
    }

    if (s.schedulerEnabled && s.nextRunAt) {
      $('val-next-run').textContent = formatRelative(s.nextRunAt);
      $('val-interval').textContent = t('status.interval', {
        m: s.intervalMinutes,
        t: formatTime(s.nextRunAt),
      });
    } else {
      $('val-next-run').textContent = t('status.disabled');
      $('val-interval').textContent = t('status.schedulerOff');
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

async function loadFeed() {
  const container = $('feed-list');
  if (!container) return;
  container.innerHTML = `<p class="hint">${t('feed.loading')}</p>`;
  try {
    const activities = await fetchJson('/api/feed');
    if (!activities.length) {
      container.innerHTML = `<p class="hint feed-empty">${t('feed.empty')}</p>`;
      return;
    }
    container.innerHTML = '';
    activities.forEach(act => {
      const card = document.createElement('div');
      card.className = 'feed-card';
      card.title = t('feed.kudo.openActivity');

      const reasonKey = `reason.${act.reason}`;
      const reasonLabel = t(reasonKey) !== reasonKey ? t(reasonKey) : act.reason;
      const decisionClass = act.give_kudos ? 'feed-decision-give' : 'feed-decision-skip';
      const decisionText  = act.give_kudos
        ? t('feed.decision.give')
        : t('feed.decision.skip', { reason: reasonLabel });

      const kudosBadge = act.has_kudoed
        ? `<span class="feed-kudo-badge feed-kudo-done">${t('feed.kudo.done')}</span>`
        : `<span class="feed-kudo-badge feed-kudo-pending">${t('feed.kudo.pending')}</span>`;

      const statsParts = Object.entries(act.stats)
        .map(([k, v]) => `<span class="feed-stat"><strong>${k}:</strong> ${v}</span>`)
        .join('');
      const statsHtml = statsParts ? `<div class="feed-stats">${statsParts}</div>` : '';
      const sportLabel = act.sport_type ? formatSportLabel(act.sport_type) : '—';

      // Kudos button — only shown when kudos haven't been given yet
      const kudosBtnHtml = !act.has_kudoed
        ? `<button class="feed-kudo-btn" data-activity-id="${act.activity_id}">${t('feed.kudo.give')}</button>`
        : '';

      card.innerHTML = `
        <div class="feed-card-header">
          <span class="feed-sport">${sportLabel}</span>
          ${kudosBadge}
        </div>
        <div class="feed-card-body">
          <div class="feed-activity-name">${act.activity_name || t('feed.noName')}</div>
          <div class="feed-athlete-name">${act.athlete_name}</div>
          ${statsHtml}
        </div>
        <div class="feed-card-footer">
          <span class="feed-decision ${decisionClass}">${decisionText}</span>
          ${kudosBtnHtml}
        </div>
      `;

      // Open activity on Strava when clicking anywhere on the card
      const activityUrl = `https://www.strava.com/activities/${act.activity_id}`;
      card.addEventListener('click', (e) => {
        // Don't navigate when the kudos button was clicked
        if (e.target.closest('.feed-kudo-btn')) return;
        window.open(activityUrl, '_blank', 'noopener,noreferrer');
      });

      // Kudos button handler
      const kudosBtn = card.querySelector('.feed-kudo-btn');
      if (kudosBtn) {
        kudosBtn.addEventListener('click', async (e) => {
          e.stopPropagation();
          kudosBtn.disabled = true;
          kudosBtn.textContent = t('feed.kudo.giving');
          try {
            const res = await fetchJson(`/api/kudos/${act.activity_id}`, { method: 'POST' });
            if (res.ok) {
              // Update badge to "done" and remove button
              const badge = card.querySelector('.feed-kudo-badge');
              if (badge) {
                badge.className = 'feed-kudo-badge feed-kudo-done';
                badge.textContent = t('feed.kudo.done');
              }
              kudosBtn.remove();
            } else {
              kudosBtn.disabled = false;
              kudosBtn.textContent = t('feed.kudo.give');
            }
          } catch {
            kudosBtn.disabled = false;
            kudosBtn.textContent = t('feed.kudo.give');
          }
        });
      }

      container.appendChild(card);
    });
  } catch (err) {
    const is401 = err.message && (
      err.message.includes('AUTH_') ||
      err.message.includes('401') ||
      err.message.toLowerCase().includes('cookie')
    );
    container.innerHTML = is401
      ? `<p class="hint feed-error">${t('feed.auth.error')}</p>`
      : `<p class="hint feed-error">${t('feed.load.error', { msg: err.message })}</p>`;
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

  // Apply static translations for the initial language
  applyStaticTranslations();

  initLangSelect();
  initTabs();
  initConfigTab();
  initDefaultsTab();
  initSettingsTab();
  initFeedTab();
  initRunButtons();
  initRevealButtons();
  initAthleteSearchModal();

  await Promise.allSettled([
    loadConfig().catch(err => toast(t('toast.config.loadError', { msg: err.message }), 'error')),
    loadDefaults().catch(err => toast(t('toast.defaults.loadError', { msg: err.message }), 'error')),
    loadSettings().catch(err => toast(t('toast.settings.loadError', { msg: err.message }), 'error')),
  ]);

  await pollStatus();
  setInterval(pollStatus, 10000);
}

init().catch(err => console.error('[init]', err));
