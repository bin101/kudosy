// ── Kudosy UI — stats.js ─────────────────────────────────────────────────────
// Statistics tab: run history chart and aggregations.

import { $ } from './dom.js';
import { fetchJson } from './api.js';
import { formatSportLabel } from './format.js';
import { t } from './i18n.js';

// ── Helpers ───────────────────────────────────────────────────────────────────

/** Format seconds as "1h 03min" or "45min". */
function formatDuration(seconds) {
  if (!seconds) return '—';
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  return h > 0 ? `${h}h ${String(m).padStart(2, '0')}min` : `${m}min`;
}

/** Group ISO timestamp into YYYY-MM-DD. */
function toDay(isoString) {
  return isoString ? isoString.slice(0, 10) : null;
}

// ── Canvas bar chart ──────────────────────────────────────────────────────────

/**
 * Draw a minimal bar chart on a <canvas> element.
 * @param {HTMLCanvasElement} canvas
 * @param {{ label: string, value: number }[]} data  - bars, in display order
 * @param {{ barColor?: string, labelColor?: string, maxBars?: number }} opts
 */
function drawBarChart(canvas, data, opts = {}) {
  const { barColor = '#6366f1', labelColor = '#64748b', maxBars = 14 } = opts;
  const slice = data.slice(-maxBars);
  if (!slice.length) return;

  const dpr = window.devicePixelRatio || 1;
  const W   = canvas.clientWidth;
  const H   = canvas.clientHeight;
  canvas.width  = W * dpr;
  canvas.height = H * dpr;
  const ctx = canvas.getContext('2d');
  ctx.scale(dpr, dpr);

  const pad    = { top: 8, right: 8, bottom: 28, left: 8 };
  const maxVal = Math.max(...slice.map(d => d.value), 1);
  const chartW = W - pad.left - pad.right;
  const chartH = H - pad.top - pad.bottom;
  const barW   = Math.max(4, Math.floor(chartW / slice.length) - 4);

  ctx.clearRect(0, 0, W, H);

  slice.forEach((d, i) => {
    const x      = pad.left + i * (chartW / slice.length) + (chartW / slice.length - barW) / 2;
    const barH   = Math.round((d.value / maxVal) * chartH);
    const y      = pad.top + chartH - barH;

    // Bar
    ctx.fillStyle = barColor;
    ctx.beginPath();
    ctx.roundRect(x, y, barW, barH, 3);
    ctx.fill();

    // Value label (above bar)
    if (d.value > 0) {
      ctx.fillStyle   = barColor;
      ctx.font        = `bold ${Math.max(9, barW > 16 ? 11 : 9)}px system-ui`;
      ctx.textAlign   = 'center';
      ctx.fillText(d.value, x + barW / 2, y - 2);
    }

    // X-axis label (date or sport name, below chart area)
    ctx.fillStyle   = labelColor;
    ctx.font        = `${Math.max(8, barW > 16 ? 10 : 8)}px system-ui`;
    ctx.textAlign   = 'center';
    const label     = d.label.length > 6 ? d.label.slice(5) : d.label; // "MM-DD" from "YYYY-MM-DD"
    ctx.fillText(label, x + barW / 2, pad.top + chartH + 16);
  });
}

// ── Stats aggregation & render ────────────────────────────────────────────────

export async function loadStats() {
  const container = $('stats-loading');
  if (container) container.hidden = false;

  try {
    const history = await fetchJson('/api/history?limit=500');

    // ── Summary cards ──────────────────────────────────────────────────────
    const real = history.filter(e => !e.dry_run && e.success);
    const totalRuns  = history.length;
    const totalKudos = real.reduce((s, e) => s + (e.given || 0), 0);
    const dryRuns    = history.filter(e => e.dry_run).length;

    const elTotalRuns  = $('stat-total-runs');
    const elTotalKudos = $('stat-total-kudos');
    const elDryRuns    = $('stat-dry-runs');
    if (elTotalRuns)  elTotalRuns.textContent  = totalRuns;
    if (elTotalKudos) elTotalKudos.textContent = totalKudos;
    if (elDryRuns)    elDryRuns.textContent    = dryRuns;

    // ── Daily kudos chart (last 14 days) ──────────────────────────────────
    const byDay = {};
    real.forEach(e => {
      const day = toDay(e.started_at);
      if (day) byDay[day] = (byDay[day] || 0) + (e.given || 0);
    });
    // Build a continuous 14-day window
    const today     = new Date();
    const dailyData = [];
    for (let i = 13; i >= 0; i--) {
      const d   = new Date(today);
      d.setDate(d.getDate() - i);
      const key = d.toISOString().slice(0, 10);
      dailyData.push({ label: key, value: byDay[key] || 0 });
    }
    const canvasDaily = $('chart-kudos-daily');
    if (canvasDaily) drawBarChart(canvasDaily, dailyData);

    // ── Last 20 runs detail table ──────────────────────────────────────────
    const tbody = $('history-tbody');
    if (tbody) {
      tbody.innerHTML = '';
      history.slice(0, 20).forEach(e => {
        const tr = document.createElement('tr');
        const date = e.started_at ? e.started_at.slice(0, 16).replace('T', ' ') : '—';
        const kudos = e.dry_run
          ? `(${e.would_give ?? 0} ${t('stats.simulated')})`
          : String(e.given ?? 0);
        const icon = !e.success ? '❌' : e.dry_run ? '🔍' : '✅';
        tr.innerHTML = `
          <td>${date}</td>
          <td>${icon}</td>
          <td>${e.total ?? 0}</td>
          <td>${kudos}</td>
        `;
        tbody.appendChild(tr);
      });
      if (!history.length) {
        const tr = document.createElement('tr');
        tr.innerHTML = `<td colspan="4" class="hint" style="text-align:center">${t('stats.noData')}</td>`;
        tbody.appendChild(tr);
      }
    }

  } catch (err) {
    const errEl = $('stats-error');
    if (errEl) {
      errEl.textContent = t('stats.loadError', { msg: err.message });
      errEl.hidden = false;
    }
  } finally {
    const container2 = $('stats-loading');
    if (container2) container2.hidden = true;
  }
}

export function initStatsTab() {
  const btn = $('btn-refresh-stats');
  if (btn) btn.addEventListener('click', loadStats);
}
