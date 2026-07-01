// ── Kudosy UI — format.js ────────────────────────────────────────────────────
// Pure display-formatting helpers (dates, times, sport labels).

import { t, currentLang, localeFor } from './i18n.js';

/** Format an ISO timestamp relative to now, e.g. "vor 3 min (14:22)". */
export function formatRelative(isoString) {
  if (!isoString) return '—';
  const d = new Date(isoString);
  const diff = Date.now() - d.getTime();
  const timeStr = d.toLocaleTimeString(localeFor(currentLang()), { hour: '2-digit', minute: '2-digit' });
  if (diff < 0) {
    const s = Math.round(-diff / 1000);
    if (s < 60) return `${t('time.inSeconds', { n: s })} (${timeStr})`;
    const m = Math.round(s / 60);
    if (m < 60) return `${t('time.inMinutes', { n: m })} (${timeStr})`;
    return `${t('time.inHours', { n: Math.round(m / 60) })} (${timeStr})`;
  }
  const s = Math.round(diff / 1000);
  if (s < 60) return `${t('time.agoSeconds', { n: s })} (${timeStr})`;
  const m = Math.round(s / 60);
  if (m < 60) return `${t('time.agoMinutes', { n: m })} (${timeStr})`;
  const h = Math.round(m / 60);
  if (h < 24) return `${t('time.agoHours', { n: h })} (${timeStr})`;
  return d.toLocaleString(localeFor(currentLang()), { dateStyle: 'short', timeStyle: 'short' });
}

/** Format an ISO timestamp as HH:MM. */
export function formatTime(isoString) {
  if (!isoString) return '—';
  return new Date(isoString).toLocaleTimeString(localeFor(currentLang()), {
    hour: '2-digit',
    minute: '2-digit',
  });
}

/** "MountainBikeRide" → "Mountain Bike Ride" */
export function formatSportLabel(type) {
  return type.replace(/([A-Z])/g, ' $1').trim();
}
