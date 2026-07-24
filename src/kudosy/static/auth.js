// ── Kudosy UI — auth.js ──────────────────────────────────────────────────────
// Optional login gate: blocks the app behind a password overlay when the
// server has KUDOSY_AUTH_PASSWORD configured. A no-op (instant resolve) when
// it isn't — see GET /api/auth-status.

import { $ } from './dom.js';
import { fetchJson } from './api.js';
import { t } from './i18n.js';

// Resolves once a valid session exists; re-used so a burst of concurrent
// 401s (e.g. several in-flight requests when a session expires) only ever
// shows one overlay instance instead of stacking submit handlers.
let _overlayPromise = null;

/**
 * On app start: check auth-status and, if a login is required and no valid
 * session exists yet, block until the user logs in successfully. Reveals the
 * logout button whenever auth is active (whether or not this call itself
 * had to show the overlay).
 */
export async function ensureAuthenticated() {
  let status;
  try {
    status = await fetchJson('/api/auth-status');
  } catch {
    // Don't let a broken auth-status check block the whole app from loading.
    return;
  }

  if (status.authRequired) {
    const logoutBtn = $('btn-logout');
    if (logoutBtn) logoutBtn.hidden = false;
  }

  if (!status.authRequired || status.authenticated) return;
  await showLoginOverlay();
}

/** Show the login overlay; resolves once a correct password was submitted. */
export function showLoginOverlay() {
  if (_overlayPromise) return _overlayPromise;

  _overlayPromise = new Promise(resolve => {
    const overlay = $('login-overlay');
    const form = $('login-form');
    const input = $('login-password');
    const errorEl = $('login-error');
    if (!overlay || !form || !input) {
      // Markup missing (shouldn't happen) — don't hang app init forever.
      resolve();
      return;
    }

    overlay.hidden = false;
    input.value = '';
    input.focus();

    const onSubmit = async e => {
      e.preventDefault();
      if (errorEl) errorEl.hidden = true;
      const submitBtn = form.querySelector('button[type="submit"]');
      if (submitBtn) submitBtn.disabled = true;

      try {
        await fetchJson('/api/login', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ password: input.value }),
        });
        form.removeEventListener('submit', onSubmit);
        overlay.hidden = true;
        _overlayPromise = null;
        resolve();
      } catch (err) {
        if (errorEl) {
          errorEl.textContent = err.message || t('login.error.generic');
          errorEl.hidden = false;
        }
        input.value = '';
        input.focus();
      } finally {
        if (submitBtn) submitBtn.disabled = false;
      }
    };
    form.addEventListener('submit', onSubmit);
  });

  return _overlayPromise;
}

/** Wire the header logout button (visible only once auth is confirmed active). */
export function initLogoutButton() {
  const btn = $('btn-logout');
  if (!btn) return;
  btn.addEventListener('click', async () => {
    try {
      await fetchJson('/api/logout', { method: 'POST' });
    } catch {
      // best-effort — reload regardless so the overlay re-gates the app
    }
    window.location.reload();
  });
}
