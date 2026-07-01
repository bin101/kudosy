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

function setButtonLoading(btn, loading) {
  if (!btn) return;
  if (loading) {
    btn._savedHTML = btn.innerHTML;
    btn.innerHTML = '<span class="spinner" aria-hidden="true"></span>';
    btn.disabled = true;
    btn.classList.add('is-loading');
  } else {
    if (btn._savedHTML !== undefined) btn.innerHTML = btn._savedHTML;
    btn.disabled = false;
    btn.classList.remove('is-loading');
    delete btn._savedHTML;
  }
}

function formatRelative(isoString) {
  if (!isoString) return '—';
  const d = new Date(isoString);
  const diff = Date.now() - d.getTime();
  const timeStr = d.toLocaleTimeString(localeFor(currentLang()), { hour: '2-digit', minute: '2-digit' });
  if (diff < 0) {
    const s = Math.round(-diff / 1000);
    if (s < 60) return `${t('time.inSeconds', { n: s })} (${timeStr})`;
    const m = Math.round(s / 60);
    if (m < 60) return `${t('time.inMinutes', { n: m })} (${timeStr})`;
    return `${t('time.inHours', { n: Math.round(m / 60) })} (${timeStr})`;
  }
  const s = Math.round(diff / 1000);
  if (s < 60) return `${t('time.agoSeconds', { n: s })} (${timeStr})`;
  const m = Math.round(s / 60);
  if (m < 60) return `${t('time.agoMinutes', { n: m })} (${timeStr})`;
  const h = Math.round(m / 60);
  if (h < 24) return `${t('time.agoHours', { n: h })} (${timeStr})`;
  return d.toLocaleString(localeFor(currentLang()), { dateStyle: 'short', timeStyle: 'short' });
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

let sportTypes      = [];
let sportCategories = {};   // { FootSports: [...], CycleSports: [...], … }
// The five canonical category names — used to distinguish a category-keyed row from
// a sport-keyed row when reading the rules tables back.
const CATEGORY_NAME_SET = new Set([
  'FootSports', 'CycleSports', 'WaterSports', 'WinterSports', 'OtherSports',
]);
let athleteLabels = {};
let athleteAvatars = {};
let pollTimer     = null;
let feedActivities = [];
let feedFetchedAt  = null;
let feedLoaded     = false;   // true after the first successful feed fetch
let feedFilter     = { status: 'all', text: '', sport: '' };

// ── Run-button spinner state ───────────────────────────────────────────────────
// The button whose spinner is currently active (null when idle).
let runningButton      = null;
// The lastRun.finished_at that was current when the user clicked Run/DryRun.
// pollStatus() clears the spinner once a *newer* finished_at appears.
let runStartStamp      = null;
// Updated by pollStatus() every tick so startRun() can snapshot it.
let currentLastRunStamp = null;

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
      if (activeFeedPane) {
        // Update sport dropdown "all sports" label if already populated
        const sportSel = $('feed-filter-sport');
        if (sportSel && sportSel.options.length > 0) {
          sportSel.options[0].textContent = t('feed.filter.allSports');
        }
        if (feedActivities.length) renderFeed();
        else loadFeed();
      }
    });
    // Keep select in sync (applyStaticTranslations won't touch it)
    sel.value = sel.value;
  });
}

// ── Tabs ──────────────────────────────────────────────────────────────────────

function activateTab(tabName) {
  const btn = document.querySelector(`.tab[data-tab="${tabName}"]`);
  if (!btn) return;
  document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
  document.querySelectorAll('.tab-pane').forEach(p => p.classList.remove('active'));
  btn.classList.add('active');
  const pane = $(`tab-${tabName}`);
  if (pane) pane.classList.add('active');
  location.hash = tabName;
  if (tabName === 'log') startPolling();
  else if (tabName === 'feed') {
    stopPolling(); pollStatus();
    // Only fetch from Strava on first visit; use cached data on tab switches.
    // The Refresh button is the explicit way to reload.
    if (feedLoaded) renderFeed(); else loadFeed();
  }
  else { stopPolling(); pollStatus(); }
}

function initTabs() {
  document.querySelectorAll('.tab').forEach(btn => {
    btn.addEventListener('click', () => activateTab(btn.dataset.tab));
  });

  // Restore the last active tab from the URL hash, fall back to 'feed'.
  const validTabs = new Set(['feed', 'config', 'log']);
  const hashTab = location.hash.slice(1);
  activateTab(validTabs.has(hashTab) ? hashTab : 'feed');
}

// ── Sport type <select> ───────────────────────────────────────────────────────

function buildSportTypeSelect(selectedType = '') {
  const sel = document.createElement('select');
  sel.className = 'sport-type-select';

  // Blank placeholder (always first, outside any optgroup)
  const blank = document.createElement('option');
  blank.value = '';
  blank.textContent = t('table.sportType.placeholder');
  if (!selectedType) blank.selected = true;
  sel.appendChild(blank);

  let found = !selectedType;

  // Prefer the grouped format when category data is available
  const hasCats = Object.keys(sportCategories).length > 0;
  const cats = hasCats ? sportCategories : { '': sportTypes };

  for (const [cat, sports] of Object.entries(cats)) {
    if (!sports.length) continue;

    let container;
    if (hasCats) {
      container = document.createElement('optgroup');
      const catLabel = t(`category.${cat}`);
      container.label = (catLabel !== `category.${cat}`) ? catLabel : cat;

      // Selectable category option — selecting it applies the rule to all members
      const catOpt = document.createElement('option');
      catOpt.value = cat;
      catOpt.className = 'opt-category';
      const allLabel = t('table.category.all');
      catOpt.textContent = allLabel !== 'table.category.all'
        ? allLabel.replace('{cat}', container.label)
        : `★ ${container.label}`;
      if (cat === selectedType) { catOpt.selected = true; found = true; }
      container.appendChild(catOpt);
    } else {
      container = sel;
    }

    for (const type of sports) {
      const opt = document.createElement('option');
      opt.value = type;
      opt.textContent = formatSportLabel(type);
      if (type === selectedType) { opt.selected = true; found = true; }
      container.appendChild(opt);
    }

    if (hasCats) sel.appendChild(container);
  }

  // Fallback: a saved value that is no longer in the active lists
  if (!found && selectedType) {
    const opt = document.createElement('option');
    opt.value = selectedType;
    opt.textContent = `${formatSportLabel(selectedType)} ↑`;
    opt.selected = true;
    // Insert right after the blank option; children[1] may be an <optgroup>
    // when categories are loaded, but insertBefore still works correctly.
    sel.insertBefore(opt, sel.children[1] || null);
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

/**
 * Read all rows from a rules table.
 * Returns { sport: {Run: 5, …}, category: {FootSports: 8, …} }
 * A row is "category" when its select value is one of the five CATEGORY_NAME_SET names.
 */
function getRulesFromTable(tbody) {
  const sport    = {};
  const category = {};
  tbody.querySelectorAll('tr').forEach(tr => {
    const sel   = tr.querySelector('select');
    const numIn = tr.querySelector('input[type="number"]');
    if (!sel || !numIn) return;
    const key = sel.value.trim();
    const raw = numIn.value.trim();
    if (key && raw !== '') {
      const val = parseFloat(raw);
      if (!isNaN(val)) {
        if (CATEGORY_NAME_SET.has(key)) category[key] = val;
        else sport[key] = val;
      }
    }
  });
  return { sport, category };
}

/**
 * Populate a rules table from two dicts: per-sport rules and per-category rules.
 * Both are loaded into the same table; the select in each row distinguishes them.
 */
function populateRulesTable(tbody, sportRules, categoryRules) {
  tbody.innerHTML = '';
  for (const [type, val] of Object.entries(sportRules || {})) {
    addRuleRow(tbody, type, val);
  }
  for (const [cat, val] of Object.entries(categoryRules || {})) {
    addRuleRow(tbody, cat, val);
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
function addAthleteManagedRow(listEl, id = '', name = '', mode = 'deny', avatarUrl = '') {
  const li = document.createElement('li');
  li.className = 'athlete-manage-row';
  li.dataset.athleteId = id;

  const displayName = name || (id ? (athleteLabels[id] || id) : '');
  const resolvedAvatar = avatarUrl || (id ? (athleteAvatars[id] || '') : '');

  const avatar = document.createElement('span');
  avatar.className = 'athlete-avatar';
  if (resolvedAvatar) {
    const img = document.createElement('img');
    img.src = resolvedAvatar;
    img.alt = displayName;
    img.loading = 'lazy';
    img.onerror = () => {
      img.remove();
      avatar.textContent = displayName ? displayName[0].toUpperCase() : '?';
    };
    avatar.appendChild(img);
  } else {
    avatar.textContent = displayName ? displayName[0].toUpperCase() : '?';
  }

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
        if (athlete.avatarUrl) athleteAvatars[athlete.id] = athlete.avatarUrl;
        addAthleteManagedRow($('athlete-manage-list'), athlete.id, athlete.name, 'deny', athlete.avatarUrl || '');
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
  const [cfg, labels, avatars] = await Promise.all([
    fetchJson('/api/config'),
    fetchJson('/api/athlete-labels').catch(() => ({})),
    fetchJson('/api/athlete-avatars').catch(() => ({})),
  ]);
  athleteLabels = labels;
  athleteAvatars = avatars;

  $('cookieInput').value    = cfg.stravaSessionCookie || '';
  $('athleteIdInput').value = cfg.athleteId || '';

  // Catch-all thresholds
  $('catchAllDist').value = cfg.catchAll?.minDistance ?? 0;
  $('catchAllTime').value = cfg.catchAll?.minTime ?? 0;

  // Unified athlete management list: merge ignoreAthletes + allowAthletes
  const manageList = $('athlete-manage-list');
  manageList.innerHTML = '';
  for (const id of (cfg.ignoreAthletes || [])) {
    addAthleteManagedRow(manageList, id, athleteLabels[id] || '', 'deny', athleteAvatars[id] || '');
  }
  for (const id of (cfg.allowAthletes || [])) {
    addAthleteManagedRow(manageList, id, athleteLabels[id] || '', 'allow', athleteAvatars[id] || '');
  }

  populateRulesTable($('tbody-distance'), cfg.kudoRules?.minDistance, cfg.kudoRules?.categoryMinDistance);
  populateRulesTable($('tbody-time'),     cfg.kudoRules?.minTime,     cfg.kudoRules?.categoryMinTime);

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
      catchAll: {
        minDistance: parseFloat($('catchAllDist').value) || 0,
        minTime:     parseFloat($('catchAllTime').value) || 0,
      },
      kudoRules: (() => {
        const dist = getRulesFromTable($('tbody-distance'));
        const time = getRulesFromTable($('tbody-time'));
        return {
          minDistance:         dist.sport,
          minTime:             time.sport,
          categoryMinDistance: dist.category,
          categoryMinTime:     time.category,
          activityNames:       getListValues($('activity-names-list')),
        };
      })(),
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

// ── Settings tab ──────────────────────────────────────────────────────────────

// ── Schedule matrix helpers ───────────────────────────────────────────────────

/** Render the 7×24 schedule matrix into #schedule-matrix with drag-to-paint support.
 *  On narrow screens (≤768px) the matrix is transposed: 7 days as columns, 24 hours
 *  as rows — no horizontal scrolling, natural vertical scroll. All data-row/data-col
 *  attributes remain unchanged (day=row, hour=col), so the paint engine and serialiser
 *  work identically in both orientations. */
function renderScheduleMatrix(matrix) {
  const container = $('schedule-matrix');
  if (!container) return;
  container.innerHTML = '';

  const days = t('settings.schedule.days') || ['Mo', 'Di', 'Mi', 'Do', 'Fr', 'Sa', 'So'];
  // Display order: 1, 2, …, 23, 0  (midnight at the end of the day, not the beginning)
  const hours = Array.from({ length: 24 }, (_, i) => (i + 1) % 24);

  // Switch to portrait/transposed only when there isn't enough room for the horizontal
  // layout. Measure the actual container width instead of using a fixed breakpoint so
  // wider devices (e.g. iPad Mini at 768 px) stay in landscape.
  // Minimum width: corner 36px + 24 slots×24px + 24 gaps×2px = 660px.
  const LANDSCAPE_MIN_WIDTH = 36 + 24 * 24 + 24 * 2; // 660px
  const wrap = $('schedule-matrix-wrap');
  // offsetWidth is 0 when the tab is hidden — fall back to viewport minus card padding.
  const availableWidth = (wrap && wrap.offsetWidth > 0) ? wrap.offsetWidth : window.innerWidth - 88;
  const portrait = availableWidth < LANDSCAPE_MIN_WIDTH;
  container.classList.toggle('transposed', portrait);

  // ── Shared cell factories (data attributes are orientation-independent) ────
  function makeCorner() {
    const el = document.createElement('div');
    el.className = 'schedule-cell schedule-corner';
    return el;
  }

  function makeHourLabel(h) {
    const el = document.createElement('div');
    el.className = 'schedule-cell schedule-hour-label';
    // Portrait: zero-padded "01"…"23"/"00"; landscape: plain number
    el.textContent = portrait ? String(h).padStart(2, '0') : h;
    el.dataset.col = h;
    el.title = `Toggle hour ${h} (all days)`;
    el.addEventListener('click', () => toggleScheduleColumn(h));
    return el;
  }

  function makeDayLabel(d) {
    const el = document.createElement('div');
    el.className = 'schedule-cell schedule-day-label';
    el.textContent = days[d] ?? d;
    el.dataset.row = d;
    el.title = `Toggle ${days[d] ?? d} (all hours)`;
    el.addEventListener('click', () => toggleScheduleRow(d));
    return el;
  }

  function makeSlot(d, h) {
    const el = document.createElement('div');
    const allowed = matrix[d]?.[h] !== false; // undefined → allowed
    el.className = 'schedule-cell schedule-slot' + (allowed ? ' allowed' : '');
    el.dataset.row = d;
    el.dataset.col = h;
    return el;
  }

  if (!portrait) {
    // ── Landscape: hours across top, days down the left ──────────────────────
    const headerRow = document.createElement('div');
    headerRow.className = 'schedule-row schedule-header';
    headerRow.appendChild(makeCorner());
    for (const h of hours) headerRow.appendChild(makeHourLabel(h));
    container.appendChild(headerRow);

    for (let d = 0; d < 7; d++) {
      const row = document.createElement('div');
      row.className = 'schedule-row';
      row.appendChild(makeDayLabel(d));
      for (const h of hours) row.appendChild(makeSlot(d, h));
      container.appendChild(row);
    }
  } else {
    // ── Portrait: days across top, hours down the left ────────────────────────
    // The paint engine reads data-row (day) and data-col (hour) — unchanged.
    const headerRow = document.createElement('div');
    headerRow.className = 'schedule-row schedule-header';
    headerRow.appendChild(makeCorner());
    for (let d = 0; d < 7; d++) headerRow.appendChild(makeDayLabel(d));
    container.appendChild(headerRow);

    for (const h of hours) {
      const row = document.createElement('div');
      row.className = 'schedule-row';
      row.appendChild(makeHourLabel(h));
      for (let d = 0; d < 7; d++) row.appendChild(makeSlot(d, h));
      container.appendChild(row);
    }
  }

  // ── Rectangle-select drag (mouse + touch) ────────────────────────────────
  // State is local to this render call; replaced on every re-render.
  let painting       = false;
  let paintValue     = false;   // the value we're painting (true = allow, false = block)
  let paintStart     = null;    // { row, col } of the cell where the drag started
  let dragSnapshot   = null;    // bool[7][24] — matrix state at the moment drag began

  // O(1) cell lookup built during the render above
  const cellMap = {};
  container.querySelectorAll('.schedule-slot').forEach(c => {
    cellMap[`${c.dataset.row},${c.dataset.col}`] = c;
  });

  function slotFromTarget(el) {
    return el && el.classList && el.classList.contains('schedule-slot') ? el : null;
  }

  function snapshotNow() {
    const snap = [];
    for (let d = 0; d < 7; d++) {
      const row = [];
      for (let h = 0; h < 24; h++) {
        row.push(cellMap[`${d},${h}`].classList.contains('allowed'));
      }
      snap.push(row);
    }
    return snap;
  }

  // Restore from snapshot, then paint all cells in the rectangle start→(endRow,endCol).
  function applyRect(endRow, endCol) {
    const r0 = Math.min(paintStart.row, endRow);
    const r1 = Math.max(paintStart.row, endRow);
    const c0 = Math.min(paintStart.col, endCol);
    const c1 = Math.max(paintStart.col, endCol);
    for (let d = 0; d < 7; d++) {
      for (let h = 0; h < 24; h++) {
        const inRect = d >= r0 && d <= r1 && h >= c0 && h <= c1;
        cellMap[`${d},${h}`].classList.toggle('allowed', inRect ? paintValue : dragSnapshot[d][h]);
      }
    }
  }

  function startDrag(slot) {
    const row = parseInt(slot.dataset.row, 10);
    const col = parseInt(slot.dataset.col, 10);
    dragSnapshot = snapshotNow();
    paintValue   = !slot.classList.contains('allowed');
    paintStart   = { row, col };
    painting     = true;
    container.classList.add('painting');
    applyRect(row, col);
  }

  function moveDrag(slot) {
    if (!painting || !slot) return;
    applyRect(parseInt(slot.dataset.row, 10), parseInt(slot.dataset.col, 10));
  }

  function stopDrag() {
    painting     = false;
    paintStart   = null;
    dragSnapshot = null;
    container.classList.remove('painting');
  }

  // Mouse
  container.addEventListener('mousedown', e => {
    const slot = slotFromTarget(e.target);
    if (!slot) return;
    e.preventDefault();
    startDrag(slot);
  });
  container.addEventListener('mouseover', e => moveDrag(slotFromTarget(e.target)));
  document.addEventListener('mouseup', stopDrag);

  // Touch
  container.addEventListener('touchstart', e => {
    const slot = slotFromTarget(e.target);
    if (!slot) return;
    e.preventDefault();
    startDrag(slot);
  }, { passive: false });
  container.addEventListener('touchmove', e => {
    if (!painting) return;
    e.preventDefault();
    const t = e.touches[0];
    moveDrag(slotFromTarget(document.elementFromPoint(t.clientX, t.clientY)));
  }, { passive: false });
  container.addEventListener('touchend', stopDrag);
  container.addEventListener('touchcancel', stopDrag);
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

  // Re-render matrix whenever the wrap changes size (viewport resize or tab becoming visible).
  // getScheduleMatrix() captures current DOM state so unsaved edits are preserved.
  const wrap = $('schedule-matrix-wrap');
  if (wrap) {
    new ResizeObserver(() => {
      const mx = $('schedule-matrix');
      if (mx && mx.children.length) renderScheduleMatrix(getScheduleMatrix());
    }).observe(wrap);
  }
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

    // Keep the spinner visible until the run we triggered actually finishes.
    // We compare finished_at rather than relying on s.running alone so that
    // even very short runs (where the poller may miss the running:true window)
    // are handled correctly.
    const finishedStamp = s.lastRun?.finished_at ?? null;
    if (runningButton) {
      const completed = !s.running && finishedStamp && finishedStamp !== runStartStamp;
      if (completed) {
        setButtonLoading(runningButton, false);
        runningButton = null;
        runStartStamp = null;
        $('btn-run').disabled = false;
      } else {
        // Run still in progress — keep spinner, keep button disabled.
        $('btn-run').disabled = true;
      }
    } else {
      // No locally-started run — mirror server state (e.g. a scheduled run).
      $('btn-run').disabled = s.running;
    }
    currentLastRunStamp = finishedStamp;

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

/** Derive a single canonical state from a feed activity. */
function activityState(act) {
  if (act.has_kudoed) return 'kudoed';
  if (act.give_kudos) return 'eligible';
  return 'skipped';
}

/** Return true if act passes the current feedFilter. */
function matchesFilter(act) {
  const { status, text, sport } = feedFilter;
  if (status !== 'all' && activityState(act) !== status) return false;
  if (sport && act.sport_type !== sport) return false;
  if (text) {
    const q       = text.toLowerCase();
    const name    = (act.activity_name || '').toLowerCase();
    const athlete = (act.athlete_name  || '').toLowerCase();
    if (!name.includes(q) && !athlete.includes(q)) return false;
  }
  return true;
}

async function loadFeed(refresh = false) {
  const container   = $('feed-list');
  const filters     = $('feed-filters');
  const refreshBtn  = $('btn-refresh-feed');
  if (!container) return;

  // Show spinner while loading
  container.innerHTML = `
    <div class="feed-loading">
      <span class="spinner spinner-lg"></span>
      <span>${t('feed.loading')}</span>
    </div>`;
  if (filters) filters.hidden = true;

  setButtonLoading(refreshBtn, true);

  try {
    const feedUrl = refresh ? '/api/feed?refresh=true' : '/api/feed';
    const feedData = await fetchJson(feedUrl);
    feedActivities = feedData.activities;
    feedFetchedAt  = feedData.fetched_at ?? null;
    feedLoaded = true;

    // Populate sport-type dropdown with types present in this feed
    const sportSel = $('feed-filter-sport');
    if (sportSel) {
      const sports = [...new Set(feedActivities.map(a => a.sport_type).filter(Boolean))].sort();
      sportSel.innerHTML = `<option value="">${t('feed.filter.allSports')}</option>`;
      sports.forEach(s => {
        const opt = document.createElement('option');
        opt.value = s;
        opt.textContent = formatSportLabel(s);
        if (s === feedFilter.sport) opt.selected = true;
        sportSel.appendChild(opt);
      });
    }

    if (filters) filters.hidden = false;
    renderFeed();
  } catch (err) {
    feedLoaded = false;
    const is401 = err.message && (
      err.message.includes('AUTH_') ||
      err.message.includes('401') ||
      err.message.toLowerCase().includes('cookie')
    );
    container.innerHTML = is401
      ? `<p class="hint feed-error">${t('feed.auth.error')}</p>`
      : `<p class="hint feed-error">${t('feed.load.error', { msg: err.message })}</p>`;
  } finally {
    setButtonLoading(refreshBtn, false);
  }
}

function updateFeedTimestamp() {
  const el = $('feed-fetched-at');
  if (!el) return;
  el.textContent = feedFetchedAt ? t('feed.fetchedAt', { time: formatRelative(feedFetchedAt) }) : '';
}

function renderFeed() {
  const container = $('feed-list');
  if (!container) return;

  updateFeedTimestamp();

  const total    = feedActivities.length;
  const filtered = feedActivities.filter(matchesFilter);

  // Update count display
  const countEl = $('feed-filter-count');
  if (countEl) {
    countEl.textContent = t('feed.filter.count', { n: filtered.length, total });
  }

  if (total === 0) {
    container.innerHTML = `<p class="hint feed-empty">${t('feed.empty')}</p>`;
    return;
  }
  if (filtered.length === 0) {
    container.innerHTML = `<p class="hint feed-empty">${t('feed.filter.none')}</p>`;
    return;
  }

  container.innerHTML = '';
  filtered.forEach(act => {
    const state = activityState(act);
    const card  = document.createElement('div');
    card.className = `feed-card feed-state-${state}`;
    card.title = t('feed.kudo.openActivity');

    const reasonKey   = `reason.${act.reason}`;
    const reasonLabel = t(reasonKey) !== reasonKey ? t(reasonKey) : act.reason;
    const decisionClass = act.give_kudos ? 'feed-decision-give' : 'feed-decision-skip';
    const decisionText  = act.give_kudos
      ? t('feed.decision.give')
      : t('feed.decision.skip', { reason: reasonLabel });

    const kudosBadge = act.has_kudoed
      ? `<span class="feed-kudo-badge feed-kudo-done">${t('feed.kudo.done')}</span>`
      : `<span class="feed-kudo-badge feed-kudo-pending">${t('feed.kudo.pending')}</span>`;

    const displayStats = (act.stats && act.stats.display) ? act.stats.display : [];
    const statsParts = displayStats
      .map(s => {
        const labelKey = `stat.${s.key}`;
        const label = t(labelKey) !== labelKey ? t(labelKey) : s.label;
        return `<span class="feed-stat"><strong>${label}:</strong> ${s.raw}</span>`;
      })
      .join('');
    const statsHtml  = statsParts ? `<div class="feed-stats">${statsParts}</div>` : '';
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
            // Keep in-memory activity in sync for future re-renders
            act.has_kudoed = true;
            act.give_kudos = false;
            act.reason = 'already';

            // Update card state class immediately
            card.className = 'feed-card feed-state-kudoed';

            // Update badge to "done" and remove button
            const badge = card.querySelector('.feed-kudo-badge');
            if (badge) {
              badge.className = 'feed-kudo-badge feed-kudo-done';
              badge.textContent = t('feed.kudo.done');
            }

            // Update decision label
            const decisionEl = card.querySelector('.feed-decision');
            if (decisionEl) {
              decisionEl.className = 'feed-decision feed-decision-skip';
              decisionEl.textContent = t('feed.decision.skip', { reason: t('reason.already') });
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
}

function initFeedTab() {
  const btn = $('btn-refresh-feed');
  if (btn) btn.addEventListener('click', () => loadFeed(true));

  // Status filter buttons
  const statusGroup = document.getElementById('feed-filter-status');
  if (statusGroup) {
    statusGroup.addEventListener('click', (e) => {
      const target = e.target.closest('.feed-filter-btn');
      if (!target) return;
      statusGroup.querySelectorAll('.feed-filter-btn').forEach(b => b.classList.remove('active'));
      target.classList.add('active');
      feedFilter.status = target.dataset.status;
      renderFeed();
    });
  }

  // Live text search
  const textInput = $('feed-filter-text');
  if (textInput) {
    textInput.addEventListener('input', () => {
      feedFilter.text = textInput.value;
      renderFeed();
    });
  }

  // Sport type filter
  const sportSel = $('feed-filter-sport');
  if (sportSel) {
    sportSel.addEventListener('change', () => {
      feedFilter.sport = sportSel.value;
      renderFeed();
    });
  }
}

// ── Run buttons ───────────────────────────────────────────────────────────────

/**
 * Fire a run request and hand off spinner ownership to pollStatus().
 *
 * The spinner is shown immediately and is NOT cleared in the finally-block —
 * pollStatus() clears it once a new lastRun.finished_at appears (i.e. when
 * the background run actually completes).  On error (e.g. 409 already running)
 * the spinner is cleared right away since there is nothing to wait for.
 */
async function startRun(btn, url) {
  if (runningButton) return;          // double-click guard
  if ($('globalDryRun')?.checked) toast(t('toast.dryRunHint'), 'info');
  runningButton  = btn;
  runStartStamp  = currentLastRunStamp;
  setButtonLoading(btn, true);
  $('btn-run').disabled = true;
  try {
    await fetchJson(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: '{}',
    });
    // Switch to the Log tab — this starts the 3-second poller which will
    // eventually detect the new finished_at and clear the spinner.
    document.querySelector('.tab[data-tab="log"]').click();
  } catch (err) {
    toast(err.message, 'error');
    // No run was started — restore the button immediately.
    setButtonLoading(btn, false);
    runningButton = null;
    $('btn-run').disabled = false;
  }
}

function initRunButtons() {
  const btnRun = $('btn-run');
  btnRun.addEventListener('click', () => {
    const url = $('globalDryRun')?.checked ? '/api/run?dryRun=1' : '/api/run';
    startRun(btnRun, url);
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
    [sportTypes, sportCategories] = await Promise.all([
      fetchJson('/api/sport-types'),
      fetchJson('/api/sport-categories'),
    ]);
  } catch {
    sportTypes      = [];
    sportCategories = {};
  }

  // Apply static translations for the initial language
  applyStaticTranslations();

  initLangSelect();
  initTabs();
  initConfigTab();
  initSettingsTab();
  initFeedTab();
  initRunButtons();
  initRevealButtons();
  initAthleteSearchModal();

  await Promise.allSettled([
    loadConfig().catch(err => toast(t('toast.config.loadError', { msg: err.message }), 'error')),
    loadSettings().catch(err => toast(t('toast.settings.loadError', { msg: err.message }), 'error')),
  ]);

  await pollStatus();
  setInterval(pollStatus, 10000);
}

init().catch(err => console.error('[init]', err));
