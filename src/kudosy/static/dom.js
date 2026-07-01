// ── Kudosy UI — dom.js ───────────────────────────────────────────────────────
// Low-level DOM helpers shared across all tab modules.

import { t } from './i18n.js';

// Shorthand for document.getElementById
export const $ = id => document.getElementById(id);

export function toast(msg, type = 'success') {
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

export function setButtonLoading(btn, loading) {
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

/** Create a × remove button that calls onClick when clicked. */
export function makeRemoveBtn(onClick) {
  const btn = document.createElement('button');
  btn.type = 'button';
  btn.className = 'btn-remove';
  btn.title = t('table.removeBtn.title');
  btn.textContent = '×';
  btn.addEventListener('click', onClick);
  return btn;
}

/** Wire up all [data-reveal] buttons (show/hide password fields). */
export function initRevealButtons() {
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
