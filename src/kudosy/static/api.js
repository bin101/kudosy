// ── Kudosy UI — api.js ───────────────────────────────────────────────────────
// Thin fetch wrappers: structured-error handling + JSON serialisation.

import { t } from './i18n.js';

export async function fetchJson(url, opts = {}) {
  const res = await fetch(url, opts);
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    // detail may be a structured {code, message} object or a plain string
    const detail = body.detail;
    if (detail && typeof detail === 'object' && detail.code) {
      const key = `error.${detail.code}`;
      const translated = t(key);
      // if key not found, fall back to the message field
      const err = new Error(translated !== key ? translated : (detail.message || `HTTP ${res.status}`));
      err.code = detail.code;
      if (detail.code === 'AUTH_REQUIRED') {
        // Session expired mid-use (or was never valid) — re-show the login
        // overlay instead of leaving the caller's own error handling (a
        // toast, usually) as the only visible feedback. Dynamic import
        // avoids a static circular dependency (auth.js imports fetchJson).
        import('./auth.js').then(m => m.showLoginOverlay());
      }
      throw err;
    }
    throw new Error(
      (typeof detail === 'string' ? detail : null) || body.error || `HTTP ${res.status}`
    );
  }
  return res.json();
}

export async function putJson(url, data) {
  return fetchJson(url, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
}
