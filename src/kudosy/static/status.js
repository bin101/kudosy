// ── Kudosy UI — status.js ────────────────────────────────────────────────────
// Status badge, log polling, run-button spinner management.

import { $, toast, setButtonLoading } from './dom.js';
import { fetchJson } from './api.js';
import { formatRelative, formatTime } from './format.js';
import { t } from './i18n.js';
import { state } from './state.js';

// ── Status polling ────────────────────────────────────────────────────────────

export async function pollStatus() {
  try {
    const s     = await fetchJson('/api/status');
    const badge = $('status-badge');
    if (s.running) {
      badge.className  = 'badge badge-running';
      badge.textContent = t('status.running');
    } else if (s.lastRun?.success === false) {
      badge.className  = 'badge badge-error';
      badge.textContent = t('status.error');
    } else if (s.lastRun?.success === true) {
      badge.className  = 'badge badge-ok';
      badge.textContent = s.lastRun.dry_run ? t('status.dryRunOk') : t('status.ok');
    } else {
      badge.className  = 'badge badge-idle';
      badge.textContent = t('status.ready');
    }

    // Keep the spinner visible until the run we triggered actually finishes.
    // We compare finished_at rather than relying on s.running alone so that
    // even very short runs (where the poller may miss the running:true window)
    // are handled correctly.
    const finishedStamp = s.lastRun?.finished_at ?? null;
    if (state.runningButton) {
      const completed = !s.running && finishedStamp && finishedStamp !== state.runStartStamp;
      if (completed) {
        setButtonLoading(state.runningButton, false);
        state.runningButton = null;
        state.runStartStamp = null;
        $('btn-run').disabled = false;
      } else {
        // Run still in progress — keep spinner, keep button disabled.
        $('btn-run').disabled = true;
      }
    } else {
      // No locally-started run — mirror server state (e.g. a scheduled run).
      $('btn-run').disabled = s.running;
    }
    state.currentLastRunStamp = finishedStamp;

    if (s.lastRun) {
      const lr           = s.lastRun;
      const successLabel = lr.success
        ? (lr.dry_run ? t('run.dryRun') : t('run.success'))
        : t('run.error');
      $('val-last-run').textContent = `${successLabel}  ${formatRelative(lr.finished_at)}`;
      $('val-last-run').style.color = lr.success ? '' : 'var(--error)';
      const kudosCount = lr.dry_run ? lr.would_give : lr.given;
      $('val-kudos').textContent = lr.dry_run
        ? t('status.kudosSimulated', { n: kudosCount })
        : t('status.kudosSent',      { n: kudosCount });
    } else {
      $('val-last-run').textContent = t('status.noRun');
      $('val-kudos').textContent    = '—';
    }

    if (s.schedulerEnabled && s.nextRunAt) {
      $('val-next-run').textContent  = formatRelative(s.nextRunAt);
      $('val-interval').textContent  = t('status.interval', {
        m: s.intervalMinutes,
        t: formatTime(s.nextRunAt),
      });
    } else {
      $('val-next-run').textContent  = t('status.disabled');
      $('val-interval').textContent  = t('status.schedulerOff');
    }

    // Auth warning banner — shown when the last run returned an auth error
    const banner = $('auth-error-banner');
    if (banner) {
      const authFailed = s.authOk === false;
      banner.hidden = !authFailed;
      if (authFailed) banner.querySelector('[data-i18n]').textContent = t('status.authError');
    }

    // Update footer version
    const versionEl = $('footer-version');
    if (versionEl && s.version) versionEl.textContent = `Kudosy v${s.version}`;
  } catch { /* ignore polling errors */ }
}

// ── Log polling ───────────────────────────────────────────────────────────────

export async function pollLog() {
  try {
    const text    = await fetch('/api/log').then(r => r.text());
    const el      = $('log-output');
    const atBottom = el.scrollHeight - el.clientHeight <= el.scrollTop + 10;
    el.textContent = text;
    if (atBottom) el.scrollTop = el.scrollHeight;
  } catch { /* ignore */ }
  await pollStatus();
}

export function startPolling() {
  stopPolling();
  pollLog();
  state.pollTimer = setInterval(() => {
    if ($('auto-refresh').checked) pollLog();
    else pollStatus();
  }, 3000);
}

export function stopPolling() {
  if (state.pollTimer) { clearInterval(state.pollTimer); state.pollTimer = null; }
}

// ── Run buttons ───────────────────────────────────────────────────────────────

/**
 * Fire a run request and hand off spinner ownership to pollStatus().
 *
 * The spinner is shown immediately and is NOT cleared in the finally-block —
 * pollStatus() clears it once a new lastRun.finished_at appears (i.e. when
 * the background run actually completes).  On error (e.g. 409 already running)
 * the spinner is cleared right away since there is nothing to wait for.
 */
export async function startRun(btn, url) {
  if (state.runningButton) return;          // double-click guard
  if ($('globalDryRun')?.checked) toast(t('toast.dryRunHint'), 'info');
  state.runningButton  = btn;
  state.runStartStamp  = state.currentLastRunStamp;
  setButtonLoading(btn, true);
  $('btn-run').disabled = true;
  try {
    await fetchJson(url, {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    '{}',
    });
    // Switch to the Log tab — this starts the 3-second poller which will
    // eventually detect the new finished_at and clear the spinner.
    document.querySelector('.tab[data-tab="log"]').click();
  } catch (err) {
    toast(err.message, 'error');
    // No run was started — restore the button immediately.
    setButtonLoading(btn, false);
    state.runningButton = null;
    $('btn-run').disabled = false;
  }
}

export function initRunButtons() {
  const btnRun = $('btn-run');
  btnRun.addEventListener('click', () => {
    const url = $('globalDryRun')?.checked ? '/api/run?dryRun=1' : '/api/run';
    startRun(btnRun, url);
  });
}
