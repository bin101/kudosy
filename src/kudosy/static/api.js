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
      throw new Error(translated !== key ? translated : (detail.message || `HTTP ${res.status}`));
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
