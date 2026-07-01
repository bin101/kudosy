// ── Kudosy UI — main.js ──────────────────────────────────────────────────────
// Application entry point: bootstrap, init order, global polling.

import { fetchJson } from './api.js';
import { applyStaticTranslations } from './i18n.js';
import { state } from './state.js';
import { toast, initRevealButtons } from './dom.js';
import { t } from './i18n.js';
import { initTabs, initLangSelect } from './tabs.js';
import { loadConfig, initConfigTab } from './config.js';
import { loadSettings, initSettingsTab } from './settings.js';
import { initFeedTab } from './feed.js';
import { pollStatus, initRunButtons } from './status.js';
import { initAthleteSearchModal } from './athletes.js';
import { initStatsTab } from './stats.js';

async function init() {
  // Fetch sport-type lists before wiring the config tab (rules selects need them)
  try {
    [state.sportTypes, state.sportCategories] = await Promise.all([
      fetchJson('/api/sport-types'),
      fetchJson('/api/sport-categories'),
    ]);
  } catch {
    state.sportTypes      = [];
    state.sportCategories = {};
  }

  // Apply static translations for the initial language before any tab renders
  applyStaticTranslations();

  initLangSelect();
  initTabs();
  initConfigTab();
  initSettingsTab();
  initFeedTab();
  initStatsTab();
  initRunButtons();
  initRevealButtons();
  initAthleteSearchModal();

  // Load config and settings in parallel, disable auto-save until both are done
  // so that DOM mutations during population don't trigger premature API calls.
  await Promise.allSettled([
    loadConfig().catch(err  => toast(t('toast.config.loadError',   { msg: err.message }), 'error')),
    loadSettings().catch(err => toast(t('toast.settings.loadError', { msg: err.message }), 'error')),
  ]);
  state.autoSaveEnabled = true;

  await pollStatus();
  setInterval(pollStatus, 10000);
}

init().catch(err => console.error('[init]', err));
