// ── Kudosy UI — theme.js ─────────────────────────────────────────────────────

import { t } from './i18n.js';

export const SUPPORTED_THEMES = ['system', 'light', 'dark'];
const STORAGE_KEY = 'kudosy.theme';

export function getTheme() {
  const stored = localStorage.getItem(STORAGE_KEY);
  return SUPPORTED_THEMES.includes(stored) ? stored : 'system';
}

export function applyTheme(mode) {
  if (mode === 'light' || mode === 'dark') {
    document.documentElement.dataset.theme = mode;
  } else {
    delete document.documentElement.dataset.theme;
  }
  const isDark =
    mode === 'dark' ||
    (mode === 'system' && window.matchMedia('(prefers-color-scheme: dark)').matches);
  document.querySelector('meta[name="theme-color"]')?.setAttribute('content', isDark ? '#1e293b' : '#6366F1');
}

export function setTheme(mode) {
  localStorage.setItem(STORAGE_KEY, mode);
  applyTheme(mode);
}

export function initThemeSelect() {
  const sel = document.getElementById('theme-select');
  if (!sel) return;

  _populateOptions(sel);
  sel.value = getTheme();
  sel.addEventListener('change', () => setTheme(sel.value));

  window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => {
    if (getTheme() === 'system') applyTheme('system');
  });
}

export function updateThemeSelectLabels() {
  const sel = document.getElementById('theme-select');
  if (!sel) return;
  const current = sel.value;
  sel.innerHTML = '';
  _populateOptions(sel);
  sel.value = current;
}

function _populateOptions(sel) {
  for (const mode of SUPPORTED_THEMES) {
    const opt       = document.createElement('option');
    opt.value       = mode;
    opt.textContent = t(`theme.${mode}`);
    sel.appendChild(opt);
  }
}
