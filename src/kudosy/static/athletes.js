// ── Kudosy UI — athletes.js ──────────────────────────────────────────────────
// Athlete managed-list rows and the athlete-search modal.

import { $, toast, makeRemoveBtn } from './dom.js';
import { fetchJson } from './api.js';
import { t } from './i18n.js';
import { state } from './state.js';

// ── Athlete managed-list helpers ─────────────────────────────────────────────
// Each athlete row has: avatar, name/id display, Allow/Deny switch, remove btn.
// The switch state determines which list (allowAthletes / ignoreAthletes) the ID
// goes into when the config is saved.

/**
 * Add an athlete to the unified management list.
 * @param {HTMLElement} listEl  - the <ul> element
 * @param {string}      id      - athlete ID
 * @param {string}      name    - display name (from cache or search)
 * @param {string}      mode    - 'allow' | 'deny' (default 'deny')
 * @param {string}      avatarUrl
 */
export function addAthleteManagedRow(listEl, id = '', name = '', mode = 'deny', avatarUrl = '') {
  const li = document.createElement('li');
  li.className = 'athlete-manage-row';
  li.dataset.athleteId = id;

  const displayName    = name || (id ? (state.athleteLabels[id] || id) : '');
  const resolvedAvatar = avatarUrl || (id ? (state.athleteAvatars[id] || '') : '');

  const avatar = document.createElement('span');
  avatar.className = 'athlete-avatar';
  if (resolvedAvatar) {
    const img = document.createElement('img');
    img.src     = resolvedAvatar;
    img.alt     = displayName;
    img.loading = 'lazy';
    img.onerror = () => {
      img.remove();
      avatar.textContent = displayName ? displayName[0].toUpperCase() : '?';
    };
    avatar.appendChild(img);
  } else {
    avatar.textContent = displayName ? displayName[0].toUpperCase() : '?';
  }

  const info     = document.createElement('span');
  info.className = 'athlete-info';
  const nameSpan = document.createElement('strong');
  nameSpan.className   = 'athlete-info-name';
  nameSpan.textContent = displayName || id;
  const idSpan   = document.createElement('small');
  idSpan.className   = 'athlete-info-id';
  idSpan.textContent = `ID: ${id}`;
  info.appendChild(nameSpan);
  info.appendChild(idSpan);

  // Allow / Deny switch
  const switchLabel = document.createElement('label');
  switchLabel.className = 'athlete-switch';

  const allowBtn = document.createElement('button');
  allowBtn.type      = 'button';
  allowBtn.className = 'athlete-switch-btn athlete-switch-allow' + (mode === 'allow' ? ' active' : '');
  allowBtn.textContent = t('config.athletes.allow');

  const denyBtn = document.createElement('button');
  denyBtn.type      = 'button';
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
 * Read the allow/deny lists from the athlete management list element.
 * @returns {{ allowAthletes: string[], ignoreAthletes: string[] }}
 */
export function getAthleteLists(listEl) {
  const allowAthletes   = [];
  const ignoreAthletes  = [];
  listEl.querySelectorAll('.athlete-manage-row').forEach(li => {
    const id = li.dataset.athleteId;
    if (!id) return;
    if (li.dataset.mode === 'allow') allowAthletes.push(id);
    else ignoreAthletes.push(id);
  });
  return { allowAthletes, ignoreAthletes };
}

// ── Athlete search modal ──────────────────────────────────────────────────────

let _athleteSearchDebounceTimer = null;

export function openAthleteSearchModal() {
  const modal = $('athlete-search-modal');
  if (!modal) return;
  modal.hidden = false;
  const input = $('athlete-search-input');
  if (input) { input.value = ''; input.focus(); }
  const results = $('athlete-search-results');
  if (results) results.innerHTML = `<p class="hint">${t('config.athletes.search.hint')}</p>`;
}

export function closeAthleteSearchModal() {
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
        img.src     = athlete.avatarUrl;
        img.alt     = athlete.name;
        img.onerror = () => { avatar.textContent = athlete.name[0]?.toUpperCase() || '?'; };
        avatar.appendChild(img);
      } else {
        avatar.textContent = athlete.name[0]?.toUpperCase() || '?';
      }

      const info   = document.createElement('span');
      info.className = 'athlete-search-item-info';
      const nameEl = document.createElement('strong');
      nameEl.textContent = athlete.name;
      const idEl   = document.createElement('small');
      idEl.textContent = `ID: ${athlete.id}`;
      info.appendChild(nameEl);
      info.appendChild(idEl);

      item.appendChild(avatar);
      item.appendChild(info);
      item.addEventListener('click', () => {
        // Cache locally for this session
        state.athleteLabels[athlete.id]  = athlete.name;
        if (athlete.avatarUrl) state.athleteAvatars[athlete.id] = athlete.avatarUrl;
        addAthleteManagedRow(
          $('athlete-manage-list'),
          athlete.id,
          athlete.name,
          'deny',
          athlete.avatarUrl || '',
        );
        closeAthleteSearchModal();
      });
      results.appendChild(item);
    });
  } catch {
    results.innerHTML = `<p class="hint feed-error">${t('config.athletes.search.error')}</p>`;
  }
}

export function initAthleteSearchModal() {
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
