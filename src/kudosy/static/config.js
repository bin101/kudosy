// ── Kudosy UI — config.js ────────────────────────────────────────────────────
// Configuration tab: credentials, athlete rules, kudo rules, auto-save.

import { $, toast, makeRemoveBtn } from './dom.js';
import { fetchJson, putJson } from './api.js';
import { formatSportLabel } from './format.js';
import { t } from './i18n.js';
import { state } from './state.js';
import { addAthleteManagedRow, getAthleteLists, openAthleteSearchModal } from './athletes.js';

// The five canonical category names — used to distinguish a category-keyed
// row from a sport-keyed row when reading the rules tables back.
const CATEGORY_NAME_SET = new Set([
  'FootSports', 'CycleSports', 'WaterSports', 'WinterSports', 'OtherSports',
]);

// ── Auto-save debounce ────────────────────────────────────────────────────────
// The guard is stored in state.autoSaveEnabled so main.js can enable it after
// the initial data load.

let _saveConfigTimer = null;

export function debouncedSaveConfig() {
  if (!state.autoSaveEnabled) return;
  clearTimeout(_saveConfigTimer);
  _saveConfigTimer = setTimeout(saveConfig, 800);
}

// ── Sport type <select> ───────────────────────────────────────────────────────

export function buildSportTypeSelect(selectedType = '') {
  const sel = document.createElement('select');
  sel.className = 'sport-type-select';

  // Blank placeholder (always first, outside any optgroup)
  const blank = document.createElement('option');
  blank.value       = '';
  blank.textContent = t('table.sportType.placeholder');
  if (!selectedType) blank.selected = true;
  sel.appendChild(blank);

  let found = !selectedType;

  // Prefer the grouped format when category data is available
  const hasCats = Object.keys(state.sportCategories).length > 0;
  const cats    = hasCats ? state.sportCategories : { '': state.sportTypes };

  for (const [cat, sports] of Object.entries(cats)) {
    if (!sports.length) continue;

    let container;
    if (hasCats) {
      container       = document.createElement('optgroup');
      const catLabel  = t(`category.${cat}`);
      container.label = (catLabel !== `category.${cat}`) ? catLabel : cat;

      // Selectable category option — selecting it applies the rule to all members
      const catOpt       = document.createElement('option');
      catOpt.value       = cat;
      catOpt.className   = 'opt-category';
      const allLabel     = t('table.category.all');
      catOpt.textContent = allLabel !== 'table.category.all'
        ? allLabel.replace('{cat}', container.label)
        : `★ ${container.label}`;
      if (cat === selectedType) { catOpt.selected = true; found = true; }
      container.appendChild(catOpt);
    } else {
      container = sel;
    }

    for (const type of sports) {
      const opt       = document.createElement('option');
      opt.value       = type;
      opt.textContent = formatSportLabel(type);
      if (type === selectedType) { opt.selected = true; found = true; }
      container.appendChild(opt);
    }

    if (hasCats) sel.appendChild(container);
  }

  // Fallback: a saved value that is no longer in the active lists
  if (!found && selectedType) {
    const opt       = document.createElement('option');
    opt.value       = selectedType;
    opt.textContent = `${formatSportLabel(selectedType)} ↑`;
    opt.selected    = true;
    sel.insertBefore(opt, sel.children[1] || null);
  }

  return sel;
}

// ── Rules table helpers ───────────────────────────────────────────────────────

export function addRuleRow(tbody, sportType = '', value = '') {
  const tr = document.createElement('tr');

  const tdType = document.createElement('td');
  tdType.appendChild(buildSportTypeSelect(sportType));

  const tdVal    = document.createElement('td');
  const numInput = document.createElement('input');
  numInput.type        = 'number';
  numInput.value       = value !== '' ? value : '';
  numInput.min         = '0';
  numInput.step        = '0.1';
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
 * @returns {{ sport: Object, category: Object }}
 * A row is "category" when its select value is one of the five CATEGORY_NAME_SET names.
 */
export function getRulesFromTable(tbody) {
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
 * Populate a rules table from per-sport and per-category dicts.
 * Both are loaded into the same table; the <select> in each row distinguishes them.
 */
export function populateRulesTable(tbody, sportRules, categoryRules) {
  tbody.innerHTML = '';
  for (const [type, val] of Object.entries(sportRules || {})) addRuleRow(tbody, type, val);
  for (const [cat, val]  of Object.entries(categoryRules || {})) addRuleRow(tbody, cat, val);
}

// ── Activity names list helpers ───────────────────────────────────────────────

export function addListItem(listEl, value = '', placeholder = '') {
  const li    = document.createElement('li');
  const input = document.createElement('input');
  input.type        = 'text';
  input.value       = value;
  input.placeholder = placeholder;
  li.appendChild(input);
  li.appendChild(makeRemoveBtn(() => li.remove()));
  listEl.appendChild(li);
  if (!value) input.focus();
}

export function getListValues(listEl) {
  return Array.from(listEl.querySelectorAll('input'))
    .map(i => i.value.trim())
    .filter(Boolean);
}

// ── Config tab I/O ────────────────────────────────────────────────────────────

export async function loadConfig() {
  const [cfg, labels, avatars] = await Promise.all([
    fetchJson('/api/config'),
    fetchJson('/api/athlete-labels').catch(() => ({})),
    fetchJson('/api/athlete-avatars').catch(() => ({})),
  ]);
  state.athleteLabels  = labels;
  state.athleteAvatars = avatars;

  $('cookieInput').value    = cfg.stravaSessionCookie || '';
  $('athleteIdInput').value = cfg.athleteId || '';

  // Catch-all thresholds
  $('catchAllDist').value = cfg.catchAll?.minDistance ?? 0;
  $('catchAllTime').value = cfg.catchAll?.minTime ?? 0;

  // Unified athlete management list: merge ignoreAthletes + allowAthletes
  const manageList = $('athlete-manage-list');
  manageList.innerHTML = '';
  for (const id of (cfg.ignoreAthletes || [])) {
    addAthleteManagedRow(manageList, id, labels[id] || '', 'deny', avatars[id] || '');
  }
  for (const id of (cfg.allowAthletes || [])) {
    addAthleteManagedRow(manageList, id, labels[id] || '', 'allow', avatars[id] || '');
  }

  populateRulesTable($('tbody-distance'), cfg.kudoRules?.minDistance,         cfg.kudoRules?.categoryMinDistance);
  populateRulesTable($('tbody-time'),     cfg.kudoRules?.minTime,             cfg.kudoRules?.categoryMinTime);

  const namesList = $('activity-names-list');
  namesList.innerHTML = '';
  for (const n of (cfg.kudoRules?.activityNames || [])) {
    addListItem(namesList, n, t('config.activityNames.placeholder'));
  }
}

export async function saveConfig() {
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
  } catch (err) {
    toast(err.message, 'error');
  }
}

// ── Config tab wiring ─────────────────────────────────────────────────────────

export function initConfigTab() {
  // Prevent accidental submit via Enter key (no submit button present).
  $('form-config').addEventListener('submit', e => e.preventDefault());

  $('btn-add-athlete').addEventListener('click', openAthleteSearchModal);
  $('btn-add-distance').addEventListener('click', () => { addRuleRow($('tbody-distance')); debouncedSaveConfig(); });
  $('btn-add-time').addEventListener('click',     () => { addRuleRow($('tbody-time'));     debouncedSaveConfig(); });
  $('btn-add-name').addEventListener('click',     () => {
    addListItem($('activity-names-list'), '', t('config.activityNames.placeholder'));
    debouncedSaveConfig();
  });

  // "Load all names" — refreshes UI labels without changing config data
  $('btn-load-all-names')?.addEventListener('click', async () => {
    try {
      const labels = await fetchJson('/api/athlete-labels');
      state.athleteLabels = { ...state.athleteLabels, ...labels };
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

  // Auto-save: native form inputs (text, number) and selects
  $('form-config').addEventListener('input',  debouncedSaveConfig);
  $('form-config').addEventListener('change', debouncedSaveConfig);

  // Auto-save: Allow/Deny toggle buttons (custom elements, not form inputs)
  $('athlete-manage-list').addEventListener('click', e => {
    if (e.target.matches('.athlete-switch-btn')) debouncedSaveConfig();
  });

  // Auto-save: dynamic list mutations (row add / remove via remove buttons)
  const observeList = el =>
    new MutationObserver(debouncedSaveConfig).observe(el, { childList: true });
  observeList($('athlete-manage-list'));
  observeList($('tbody-distance'));
  observeList($('tbody-time'));
  observeList($('activity-names-list'));
}
