// ── Kudosy UI — tabs.js ──────────────────────────────────────────────────────
// Tab switching (with URL-hash persistence) and language selector.

import { $ } from './dom.js';
import { SUPPORTED, LANG_LABELS, t, getLang, setLang } from './i18n.js';
import { state } from './state.js';
import { pollStatus, startPolling, stopPolling } from './status.js';
import { loadFeed, renderFeed } from './feed.js';
import { loadStats } from './stats.js';
import { updateThemeSelectLabels } from './theme.js';

// ── Tab switching ─────────────────────────────────────────────────────────────

export function activateTab(tabName) {
  const btn = document.querySelector(`.tab[data-tab="${tabName}"]`);
  if (!btn) return;
  document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
  document.querySelectorAll('.tab-pane').forEach(p => p.classList.remove('active'));
  btn.classList.add('active');
  const pane = $(`tab-${tabName}`);
  if (pane) pane.classList.add('active');
  location.hash = tabName;

  if (tabName === 'log') {
    startPolling();
  } else if (tabName === 'feed') {
    stopPolling();
    pollStatus();
    // Only fetch from Strava on first visit; use cached data on tab switches.
    // The Refresh button is the explicit way to reload from Strava.
    if (state.feedLoaded) renderFeed(); else loadFeed();
  } else if (tabName === 'stats') {
    stopPolling();
    pollStatus();
    // Load stats on first visit; the Refresh button handles explicit reloads.
    if (!state.statsLoaded) {
      state.statsLoaded = true;
      loadStats();
    }
  } else {
    stopPolling();
    pollStatus();
  }
}

export function initTabs() {
  document.querySelectorAll('.tab').forEach(btn => {
    btn.addEventListener('click', () => activateTab(btn.dataset.tab));
  });

  // Restore the last active tab from the URL hash, fall back to 'feed'.
  const validTabs = new Set(['feed', 'config', 'log', 'stats']);
  const hashTab   = location.hash.slice(1);
  activateTab(validTabs.has(hashTab) ? hashTab : 'feed');
}

// ── Language selector ─────────────────────────────────────────────────────────

export function initLangSelect() {
  const sel = $('lang-select');
  if (!sel) return;
  for (const lang of SUPPORTED) {
    const opt       = document.createElement('option');
    opt.value       = lang;
    opt.textContent = LANG_LABELS[lang];
    if (lang === getLang()) opt.selected = true;
    sel.appendChild(opt);
  }
  sel.addEventListener('change', () => {
    setLang(sel.value, () => {
      updateThemeSelectLabels();
      // Re-render dynamic areas after language change
      pollStatus();
      const activeFeedPane = document.querySelector('#tab-feed.active');
      if (activeFeedPane) {
        // Update sport dropdown "all sports" label if already populated
        const sportSel = $('feed-filter-sport');
        if (sportSel && sportSel.options.length > 0) {
          sportSel.options[0].textContent = t('feed.filter.allSports');
        }
        if (state.feedActivities.length) renderFeed(); else loadFeed();
      }
    });
    // Keep select in sync (applyStaticTranslations won't touch it)
    sel.value = sel.value;
  });
}
