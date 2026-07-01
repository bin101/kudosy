// ── Kudosy UI — settings.js ──────────────────────────────────────────────────
// Settings (Automation) tab: scheduler, delays, quiet-hours matrix.

import { $, toast } from './dom.js';
import { fetchJson, putJson } from './api.js';
import { t } from './i18n.js';
import { state } from './state.js';
import {
  renderScheduleMatrix,
  getScheduleMatrix,
  toggleScheduleMatrixEnabled,
} from './schedule-matrix.js';
import { pollStatus } from './status.js';

// ── Auto-save debounce ────────────────────────────────────────────────────────

let _saveSettingsTimer = null;

export function debouncedSaveSettings() {
  if (!state.autoSaveEnabled) return;
  clearTimeout(_saveSettingsTimer);
  _saveSettingsTimer = setTimeout(saveSettings, 800);
}

// ── Settings tab I/O ──────────────────────────────────────────────────────────

export async function loadSettings() {
  const s = await fetchJson('/api/settings');
  $('schedulerEnabled').checked     = s.schedulerEnabled;
  $('intervalMinutes').value         = s.intervalMinutes ?? 60;
  $('jitterMinutes').value           = s.jitterMinutes   ?? 15;
  $('globalDryRun').checked          = s.dryRun;
  $('minKudosDelaySeconds').value    = s.minKudosDelaySeconds ?? 3;
  $('maxKudosDelaySeconds').value    = s.maxKudosDelaySeconds ?? 25;
  $('shuffleOrder').checked          = s.shuffleOrder ?? true;
  $('kudosScheduleEnabled').checked  = s.kudosScheduleEnabled ?? false;
  $('timezone').value                = s.timezone ?? 'Europe/Berlin';
  $('notifyWebhookUrl').value        = s.notifyWebhookUrl ?? '';
  $('notifyOnRun').checked           = s.notifyOnRun ?? false;
  $('notifyOnAuthError').checked     = s.notifyOnAuthError ?? true;
  toggleIntervalVisibility(s.schedulerEnabled);
  toggleScheduleMatrixEnabled(s.kudosScheduleEnabled ?? false);

  // Render the schedule matrix (all-true by default)
  const matrix = s.kudosScheduleMatrix || Array.from({ length: 7 }, () => Array(24).fill(true));
  renderScheduleMatrix(matrix);
}

export function toggleIntervalVisibility(enabled) {
  const opacity = enabled ? '1' : '0.4';
  $('interval-group').style.opacity = opacity;
  $('jitter-group').style.opacity   = opacity;
  $('intervalMinutes').disabled     = !enabled;
  $('jitterMinutes').disabled       = !enabled;
}

export async function saveSettings() {
  try {
    const data = {
      schedulerEnabled:      $('schedulerEnabled').checked,
      intervalMinutes:       Math.max(5, parseInt($('intervalMinutes').value) || 60),
      jitterMinutes:         Math.max(0, parseFloat($('jitterMinutes').value) || 0),
      dryRun:                $('globalDryRun').checked,
      minKudosDelaySeconds:  Math.max(0, parseFloat($('minKudosDelaySeconds').value) || 0),
      maxKudosDelaySeconds:  Math.max(0, parseFloat($('maxKudosDelaySeconds').value) || 0),
      shuffleOrder:          $('shuffleOrder').checked,
      kudosScheduleEnabled:  $('kudosScheduleEnabled').checked,
      timezone:              $('timezone').value.trim() || 'Europe/Berlin',
      kudosScheduleMatrix:   getScheduleMatrix(),
      notifyWebhookUrl:      $('notifyWebhookUrl').value.trim(),
      notifyOnRun:           $('notifyOnRun').checked,
      notifyOnAuthError:     $('notifyOnAuthError').checked,
    };
    await putJson('/api/settings', data);
    pollStatus();
  } catch (err) {
    toast(err.message, 'error');
  }
}

// ── Settings tab wiring ───────────────────────────────────────────────────────

export function initSettingsTab() {
  // Prevent accidental submit via Enter key (no submit button present).
  $('form-settings').addEventListener('submit', e => e.preventDefault());

  // UI side-effects for toggle changes (interval visibility, matrix dim)
  $('schedulerEnabled').addEventListener('change',       e => toggleIntervalVisibility(e.target.checked));
  $('kudosScheduleEnabled').addEventListener('change',   e => toggleScheduleMatrixEnabled(e.target.checked));

  // Auto-save: native form inputs and checkboxes
  $('form-settings').addEventListener('input',  debouncedSaveSettings);
  $('form-settings').addEventListener('change', debouncedSaveSettings);

  const wrap = $('schedule-matrix-wrap');
  if (wrap) {
    // Auto-save: schedule matrix drag-paint and click-toggles (div cells, not form inputs)
    wrap.addEventListener('mouseup',  debouncedSaveSettings);
    wrap.addEventListener('touchend', debouncedSaveSettings);

    // Re-render matrix whenever the wrap changes size (viewport resize or tab becoming visible).
    // getScheduleMatrix() captures current DOM state so unsaved edits are preserved.
    new ResizeObserver(() => {
      const mx = $('schedule-matrix');
      if (mx && mx.children.length) renderScheduleMatrix(getScheduleMatrix());
    }).observe(wrap);
  }
}
