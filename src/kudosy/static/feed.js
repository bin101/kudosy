// ── Kudosy UI — feed.js ──────────────────────────────────────────────────────
// Feed tab: load, render, filter and per-card kudos button.

import { $, toast, setButtonLoading, escapeHtml } from './dom.js';
import { fetchJson } from './api.js';
import { formatSportLabel, formatRelative } from './format.js';
import { t } from './i18n.js';
import { state } from './state.js';

// ── State helpers ─────────────────────────────────────────────────────────────

/** Derive a single canonical state from a feed activity. */
export function activityState(act) {
  if (act.has_kudoed) return 'kudoed';
  if (act.give_kudos) return 'eligible';
  return 'skipped';
}

/** Return true if act passes the current feedFilter. */
export function matchesFilter(act) {
  const { status, text, sport } = state.feedFilter;
  if (status !== 'all' && activityState(act) !== status) return false;
  if (sport && act.sport_type !== sport) return false;
  if (text) {
    const q       = text.toLowerCase();
    const name    = (act.activity_name || '').toLowerCase();
    const athlete = (act.athlete_name  || '').toLowerCase();
    if (!name.includes(q) && !athlete.includes(q)) return false;
  }
  return true;
}

// ── Feed I/O ──────────────────────────────────────────────────────────────────

export async function loadFeed(refresh = false) {
  const container  = $('feed-list');
  const filters    = $('feed-filters');
  const refreshBtn = $('btn-refresh-feed');
  if (!container) return;

  // Show spinner while loading
  container.innerHTML = `
    <div class="feed-loading">
      <span class="spinner spinner-lg"></span>
      <span>${t('feed.loading')}</span>
    </div>`;
  if (filters) filters.hidden = true;

  setButtonLoading(refreshBtn, true);

  try {
    const feedUrl  = refresh ? '/api/feed?refresh=true' : '/api/feed';
    const feedData = await fetchJson(feedUrl);
    state.feedActivities = feedData.activities;
    state.feedFetchedAt  = feedData.fetched_at ?? null;
    state.feedLoaded     = true;

    // Populate sport-type dropdown with types present in this feed
    const sportSel = $('feed-filter-sport');
    if (sportSel) {
      const sports = [...new Set(state.feedActivities.map(a => a.sport_type).filter(Boolean))].sort();
      sportSel.innerHTML = `<option value="">${t('feed.filter.allSports')}</option>`;
      sports.forEach(s => {
        const opt       = document.createElement('option');
        opt.value       = s;
        opt.textContent = formatSportLabel(s);
        if (s === state.feedFilter.sport) opt.selected = true;
        sportSel.appendChild(opt);
      });
    }

    if (filters) filters.hidden = false;
    renderFeed();
  } catch (err) {
    state.feedLoaded = false;
    const is401 = err.message && (
      err.message.includes('AUTH_') ||
      err.message.includes('401') ||
      err.message.toLowerCase().includes('cookie')
    );
    container.innerHTML = is401
      ? `<p class="hint feed-error">${t('feed.auth.error')}</p>`
      : `<p class="hint feed-error">${t('feed.load.error', { msg: err.message })}</p>`;
  } finally {
    setButtonLoading(refreshBtn, false);
  }
}

// ── Feed rendering ────────────────────────────────────────────────────────────

export function updateFeedTimestamp() {
  const el = $('feed-fetched-at');
  if (!el) return;
  el.textContent = state.feedFetchedAt
    ? t('feed.fetchedAt', { time: formatRelative(state.feedFetchedAt) })
    : '';
}

export function renderFeed() {
  const container = $('feed-list');
  if (!container) return;

  updateFeedTimestamp();

  const total    = state.feedActivities.length;
  const filtered = state.feedActivities.filter(matchesFilter);

  // Update count display
  const countEl = $('feed-filter-count');
  if (countEl) countEl.textContent = t('feed.filter.count', { n: filtered.length, total });

  if (total === 0) {
    container.innerHTML = `<p class="hint feed-empty">${t('feed.empty')}</p>`;
    return;
  }
  if (filtered.length === 0) {
    container.innerHTML = `<p class="hint feed-empty">${t('feed.filter.none')}</p>`;
    return;
  }

  container.innerHTML = '';
  filtered.forEach(act => {
    const state_   = activityState(act);
    const card     = document.createElement('div');
    card.className = `feed-card feed-state-${state_}`;
    card.title     = t('feed.kudo.openActivity');

    const reasonKey   = `reason.${act.reason}`;
    const reasonLabel = t(reasonKey) !== reasonKey ? t(reasonKey) : act.reason;
    const decisionClass = act.give_kudos ? 'feed-decision-give' : 'feed-decision-skip';
    const decisionText  = act.give_kudos
      ? t('feed.decision.give')
      : t('feed.decision.skip', { reason: reasonLabel });

    const kudosBadge = act.has_kudoed
      ? `<span class="feed-kudo-badge feed-kudo-done">${t('feed.kudo.done')}</span>`
      : `<span class="feed-kudo-badge feed-kudo-pending">${t('feed.kudo.pending')}</span>`;

    const displayStats = (act.stats && act.stats.display) ? act.stats.display : [];
    const statsParts   = displayStats
      .map(s => {
        const labelKey = `stat.${s.key}`;
        // t() translations are trusted; s.label/s.raw come from the Strava feed and must be escaped.
        const label    = t(labelKey) !== labelKey ? t(labelKey) : escapeHtml(s.label);
        return `<span class="feed-stat"><strong>${label}:</strong> ${escapeHtml(s.raw)}</span>`;
      })
      .join('');
    const statsHtml  = statsParts ? `<div class="feed-stats">${statsParts}</div>` : '';
    const sportLabel = act.sport_type ? formatSportLabel(act.sport_type) : '—';

    // Kudos button — only shown when kudos haven't been given yet
    const kudosBtnHtml = !act.has_kudoed
      ? `<button class="feed-kudo-btn" data-activity-id="${act.activity_id}">${t('feed.kudo.give')}</button>`
      : '';

    card.innerHTML = `
      <div class="feed-card-header">
        <span class="feed-sport">${sportLabel}</span>
        ${kudosBadge}
      </div>
      <div class="feed-card-body">
        <div class="feed-activity-name">${act.activity_name ? escapeHtml(act.activity_name) : t('feed.noName')}</div>
        <div class="feed-athlete-name">${escapeHtml(act.athlete_name)}</div>
        ${statsHtml}
      </div>
      <div class="feed-card-footer">
        <span class="feed-decision ${decisionClass}">${decisionText}</span>
        ${kudosBtnHtml}
      </div>
    `;

    // Open activity on Strava when clicking anywhere on the card
    const activityUrl = `https://www.strava.com/activities/${act.activity_id}`;
    card.addEventListener('click', e => {
      if (e.target.closest('.feed-kudo-btn')) return;
      window.open(activityUrl, '_blank', 'noopener,noreferrer');
    });

    // Kudos button handler
    const kudosBtn = card.querySelector('.feed-kudo-btn');
    if (kudosBtn) {
      kudosBtn.addEventListener('click', async e => {
        e.stopPropagation();
        kudosBtn.disabled    = true;
        kudosBtn.textContent = t('feed.kudo.giving');
        try {
          const res = await fetchJson(`/api/kudos/${act.activity_id}`, { method: 'POST' });
          if (res.ok) {
            // Keep in-memory activity in sync for future re-renders
            act.has_kudoed = true;
            act.give_kudos = false;
            act.reason     = 'already';

            // Update card state class immediately
            card.className = 'feed-card feed-state-kudoed';

            const badge = card.querySelector('.feed-kudo-badge');
            if (badge) {
              badge.className  = 'feed-kudo-badge feed-kudo-done';
              badge.textContent = t('feed.kudo.done');
            }

            const decisionEl = card.querySelector('.feed-decision');
            if (decisionEl) {
              decisionEl.className  = 'feed-decision feed-decision-skip';
              decisionEl.textContent = t('feed.decision.skip', { reason: t('reason.already') });
            }

            kudosBtn.remove();
          } else {
            kudosBtn.disabled    = false;
            kudosBtn.textContent = t('feed.kudo.give');
          }
        } catch {
          kudosBtn.disabled    = false;
          kudosBtn.textContent = t('feed.kudo.give');
        }
      });
    }

    container.appendChild(card);
  });
}

// ── Feed tab wiring ───────────────────────────────────────────────────────────

export function initFeedTab() {
  const btn = $('btn-refresh-feed');
  if (btn) btn.addEventListener('click', () => loadFeed(true));

  // Status filter buttons
  const statusGroup = document.getElementById('feed-filter-status');
  if (statusGroup) {
    statusGroup.addEventListener('click', e => {
      const target = e.target.closest('.feed-filter-btn');
      if (!target) return;
      statusGroup.querySelectorAll('.feed-filter-btn').forEach(b => b.classList.remove('active'));
      target.classList.add('active');
      state.feedFilter.status = target.dataset.status;
      renderFeed();
    });
  }

  // Live text search
  const textInput = $('feed-filter-text');
  if (textInput) {
    textInput.addEventListener('input', () => {
      state.feedFilter.text = textInput.value;
      renderFeed();
    });
  }

  // Sport type filter
  const sportSel = $('feed-filter-sport');
  if (sportSel) {
    sportSel.addEventListener('change', () => {
      state.feedFilter.sport = sportSel.value;
      renderFeed();
    });
  }
}
