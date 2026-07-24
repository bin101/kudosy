// ── Kudosy UI — main.js ──────────────────────────────────────────────────────
// Application entry point: bootstrap, init order, global polling.

import { fetchJson } from './api.js';
import { applyStaticTranslations } from './i18n.js';
import { state } from './state.js';
import { $, toast, initRevealButtons } from './dom.js';
import { t } from './i18n.js';
import { ensureAuthenticated, initLogoutButton } from './auth.js';
import { initTabs, initLangSelect, activateTab } from './tabs.js';
import { initThemeSelect, applyTheme, getTheme } from './theme.js';
import { loadConfig, initConfigTab } from './config.js';
import { loadSettings, initSettingsTab } from './settings.js';
import { initFeedTab } from './feed.js';
import { pollStatus, initRunButtons } from './status.js';
import { initAthleteSearchModal } from './athletes.js';
import { initStatsTab } from './stats.js';
import { initBackup } from './backup.js';

async function init() {
  // Blocks here (showing a login overlay) until authenticated, if the server
  // has a login configured at all — a no-op otherwise. Must run before any
  // other /api/* call so the app never flashes real data before the gate.
  await ensureAuthenticated();
  initLogoutButton();

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

  applyTheme(getTheme());
  initThemeSelect();
  initLangSelect();
  initTabs();
  initConfigTab();
  initSettingsTab();
  initFeedTab();
  initStatsTab();
  initBackup();
  initRunButtons();
  initRevealButtons();
  initAthleteSearchModal();

  // Auth banner → jump to the config tab and focus the cookie field
  const authBanner = $('auth-error-banner');
  if (authBanner) {
    const goToCookie = () => { activateTab('config'); $('cookieInput')?.focus(); };
    authBanner.addEventListener('click', goToCookie);
    authBanner.addEventListener('keydown', e => {
      if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); goToCookie(); }
    });
  }

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
