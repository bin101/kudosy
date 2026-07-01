// ── Kudosy UI — backup.js ────────────────────────────────────────────────────
// Config export (download) and import (file pick + confirm dialog).

import { $ } from './dom.js';
import { fetchJson } from './api.js';
import { t } from './i18n.js';
import { toast } from './dom.js';

// ── Export ────────────────────────────────────────────────────────────────────

function triggerExport() {
  // Fetch the backup JSON and trigger a browser download without navigating away.
  fetchJson('/api/export')
    .then(data => {
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
      const url  = URL.createObjectURL(blob);
      const a    = document.createElement('a');
      a.href     = url;
      a.download = 'kudosy-backup.json';
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    })
    .catch(err => toast(err.message, 'error'));
}

// ── Import ────────────────────────────────────────────────────────────────────

let _pendingPayload = null;

function openImportDialog(payload) {
  _pendingPayload = payload;
  const dialog = $('import-confirm-dialog');
  if (dialog?.showModal) dialog.showModal();
}

async function confirmImport() {
  const dialog = $('import-confirm-dialog');
  if (dialog?.close) dialog.close();
  if (!_pendingPayload) return;
  try {
    await fetchJson('/api/import', {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify(_pendingPayload),
    });
    toast(t('config.backup.importSuccess'), 'success');
    // Reload config + settings UI to reflect imported values
    const { loadConfig } = await import('./config.js');
    const { loadSettings } = await import('./settings.js');
    await Promise.allSettled([loadConfig(), loadSettings()]);
  } catch (err) {
    toast(t('config.backup.importError', { msg: err.message }), 'error');
  } finally {
    _pendingPayload = null;
  }
}

function handleFileSelect(file) {
  if (!file) return;
  const reader = new FileReader();
  reader.onload = e => {
    try {
      const payload = JSON.parse(e.target.result);
      if (!payload.config || !payload.settings) {
        toast(t('config.backup.importError', { msg: 'missing config or settings' }), 'error');
        return;
      }
      openImportDialog(payload);
    } catch {
      toast(t('config.backup.importError', { msg: 'invalid JSON' }), 'error');
    }
  };
  reader.readAsText(file);
}

// ── Init ──────────────────────────────────────────────────────────────────────

export function initBackup() {
  const btnExport  = $('btn-export');
  const btnTrigger = $('btn-import-trigger');
  const fileInput  = $('import-file-input');
  const btnCancel  = $('btn-import-cancel');
  const btnConfirm = $('btn-import-confirm');

  if (btnExport)  btnExport.addEventListener('click', triggerExport);
  if (btnTrigger) btnTrigger.addEventListener('click', () => fileInput?.click());
  if (fileInput)  fileInput.addEventListener('change', e => {
    handleFileSelect(e.target.files?.[0] ?? null);
    // Reset so the same file can be re-selected after cancel
    e.target.value = '';
  });
  if (btnCancel) {
    btnCancel.addEventListener('click', () => {
      $('import-confirm-dialog')?.close();
      _pendingPayload = null;
    });
  }
  if (btnConfirm) btnConfirm.addEventListener('click', confirmImport);
}
