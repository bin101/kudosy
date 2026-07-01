// ── Kudosy UI — schedule-matrix.js ───────────────────────────────────────────
// 7×24 schedule matrix: render, toggle rows/columns, read state, dim/enable.

import { $ } from './dom.js';
import { t } from './i18n.js';

/** Render the 7×24 schedule matrix into #schedule-matrix with drag-to-paint
 *  support.  On narrow screens (≤768px) the matrix is transposed: 7 days as
 *  columns, 24 hours as rows — no horizontal scrolling, natural vertical
 *  scroll.  All data-row/data-col attributes remain unchanged (day=row,
 *  hour=col), so the paint engine and serialiser work identically in both
 *  orientations. */
export function renderScheduleMatrix(matrix) {
  const container = $('schedule-matrix');
  if (!container) return;
  container.innerHTML = '';

  const days = t('settings.schedule.days') || ['Mo', 'Di', 'Mi', 'Do', 'Fr', 'Sa', 'So'];
  // Display order: 1, 2, …, 23, 0  (midnight at the end of the day, not the beginning)
  const hours = Array.from({ length: 24 }, (_, i) => (i + 1) % 24);

  // Switch to portrait/transposed only when there isn't enough room for the
  // horizontal layout.  Measure the actual container width instead of using a
  // fixed breakpoint so wider devices (e.g. iPad Mini at 768 px) stay in
  // landscape.  Minimum width: corner 36px + 24 slots×24px + 24 gaps×2px = 660px.
  const LANDSCAPE_MIN_WIDTH = 36 + 24 * 24 + 24 * 2; // 660px
  const wrap = $('schedule-matrix-wrap');
  // offsetWidth is 0 when the tab is hidden — fall back to viewport minus card padding.
  const availableWidth = (wrap && wrap.offsetWidth > 0) ? wrap.offsetWidth : window.innerWidth - 88;
  const portrait = availableWidth < LANDSCAPE_MIN_WIDTH;
  container.classList.toggle('transposed', portrait);

  // ── Shared cell factories (data attributes are orientation-independent) ────
  function makeCorner() {
    const el = document.createElement('div');
    el.className = 'schedule-cell schedule-corner';
    return el;
  }

  function makeHourLabel(h) {
    const el = document.createElement('div');
    el.className = 'schedule-cell schedule-hour-label';
    // Portrait: zero-padded "01"…"23"/"00"; landscape: plain number
    el.textContent = portrait ? String(h).padStart(2, '0') : h;
    el.dataset.col = h;
    el.title = `Toggle hour ${h} (all days)`;
    el.addEventListener('click', () => toggleScheduleColumn(h));
    return el;
  }

  function makeDayLabel(d) {
    const el = document.createElement('div');
    el.className = 'schedule-cell schedule-day-label';
    el.textContent = days[d] ?? d;
    el.dataset.row = d;
    el.title = `Toggle ${days[d] ?? d} (all hours)`;
    el.addEventListener('click', () => toggleScheduleRow(d));
    return el;
  }

  function makeSlot(d, h) {
    const el = document.createElement('div');
    const allowed = matrix[d]?.[h] !== false; // undefined → allowed
    el.className = 'schedule-cell schedule-slot' + (allowed ? ' allowed' : '');
    el.dataset.row = d;
    el.dataset.col = h;
    return el;
  }

  if (!portrait) {
    // ── Landscape: hours across top, days down the left ──────────────────────
    const headerRow = document.createElement('div');
    headerRow.className = 'schedule-row schedule-header';
    headerRow.appendChild(makeCorner());
    for (const h of hours) headerRow.appendChild(makeHourLabel(h));
    container.appendChild(headerRow);

    for (let d = 0; d < 7; d++) {
      const row = document.createElement('div');
      row.className = 'schedule-row';
      row.appendChild(makeDayLabel(d));
      for (const h of hours) row.appendChild(makeSlot(d, h));
      container.appendChild(row);
    }
  } else {
    // ── Portrait: days across top, hours down the left ────────────────────────
    // The paint engine reads data-row (day) and data-col (hour) — unchanged.
    const headerRow = document.createElement('div');
    headerRow.className = 'schedule-row schedule-header';
    headerRow.appendChild(makeCorner());
    for (let d = 0; d < 7; d++) headerRow.appendChild(makeDayLabel(d));
    container.appendChild(headerRow);

    for (const h of hours) {
      const row = document.createElement('div');
      row.className = 'schedule-row';
      row.appendChild(makeHourLabel(h));
      for (let d = 0; d < 7; d++) row.appendChild(makeSlot(d, h));
      container.appendChild(row);
    }
  }

  // ── Rectangle-select drag (mouse + touch) ────────────────────────────────
  // State is local to this render call; replaced on every re-render.
  let painting       = false;
  let paintValue     = false;   // the value we're painting (true = allow, false = block)
  let paintStart     = null;    // { row, col } of the cell where the drag started
  let dragSnapshot   = null;    // bool[7][24] — matrix state at the moment drag began

  // O(1) cell lookup built during the render above
  const cellMap = {};
  container.querySelectorAll('.schedule-slot').forEach(c => {
    cellMap[`${c.dataset.row},${c.dataset.col}`] = c;
  });

  function slotFromTarget(el) {
    return el && el.classList && el.classList.contains('schedule-slot') ? el : null;
  }

  function snapshotNow() {
    const snap = [];
    for (let d = 0; d < 7; d++) {
      const row = [];
      for (let h = 0; h < 24; h++) {
        row.push(cellMap[`${d},${h}`].classList.contains('allowed'));
      }
      snap.push(row);
    }
    return snap;
  }

  // Restore from snapshot, then paint all cells in the rectangle start→(endRow,endCol).
  function applyRect(endRow, endCol) {
    const r0 = Math.min(paintStart.row, endRow);
    const r1 = Math.max(paintStart.row, endRow);
    const c0 = Math.min(paintStart.col, endCol);
    const c1 = Math.max(paintStart.col, endCol);
    for (let d = 0; d < 7; d++) {
      for (let h = 0; h < 24; h++) {
        const inRect = d >= r0 && d <= r1 && h >= c0 && h <= c1;
        cellMap[`${d},${h}`].classList.toggle('allowed', inRect ? paintValue : dragSnapshot[d][h]);
      }
    }
  }

  function startDrag(slot) {
    const row = parseInt(slot.dataset.row, 10);
    const col = parseInt(slot.dataset.col, 10);
    dragSnapshot = snapshotNow();
    paintValue   = !slot.classList.contains('allowed');
    paintStart   = { row, col };
    painting     = true;
    container.classList.add('painting');
    applyRect(row, col);
  }

  function moveDrag(slot) {
    if (!painting || !slot) return;
    applyRect(parseInt(slot.dataset.row, 10), parseInt(slot.dataset.col, 10));
  }

  function stopDrag() {
    painting     = false;
    paintStart   = null;
    dragSnapshot = null;
    container.classList.remove('painting');
  }

  // Mouse
  container.addEventListener('mousedown', e => {
    const slot = slotFromTarget(e.target);
    if (!slot) return;
    e.preventDefault();
    startDrag(slot);
  });
  container.addEventListener('mouseover', e => moveDrag(slotFromTarget(e.target)));
  document.addEventListener('mouseup', stopDrag);

  // Touch
  container.addEventListener('touchstart', e => {
    const slot = slotFromTarget(e.target);
    if (!slot) return;
    e.preventDefault();
    startDrag(slot);
  }, { passive: false });
  container.addEventListener('touchmove', e => {
    if (!painting) return;
    e.preventDefault();
    const touch = e.touches[0];
    moveDrag(slotFromTarget(document.elementFromPoint(touch.clientX, touch.clientY)));
  }, { passive: false });
  container.addEventListener('touchend', stopDrag);
  container.addEventListener('touchcancel', stopDrag);
}

export function toggleScheduleRow(rowIdx) {
  const slots = document.querySelectorAll(`#schedule-matrix .schedule-slot[data-row="${rowIdx}"]`);
  const anyOff = Array.from(slots).some(c => !c.classList.contains('allowed'));
  slots.forEach(c => c.classList.toggle('allowed', anyOff));
}

export function toggleScheduleColumn(colIdx) {
  const slots = document.querySelectorAll(`#schedule-matrix .schedule-slot[data-col="${colIdx}"]`);
  const anyOff = Array.from(slots).some(c => !c.classList.contains('allowed'));
  slots.forEach(c => c.classList.toggle('allowed', anyOff));
}

export function getScheduleMatrix() {
  const matrix = [];
  for (let d = 0; d < 7; d++) {
    const row = [];
    for (let h = 0; h < 24; h++) {
      const cell = document.querySelector(
        `#schedule-matrix .schedule-slot[data-row="${d}"][data-col="${h}"]`
      );
      row.push(cell ? cell.classList.contains('allowed') : true);
    }
    matrix.push(row);
  }
  return matrix;
}

/** Dim / enable the schedule matrix wrap + timezone group based on enabled. */
export function toggleScheduleMatrixEnabled(enabled) {
  const wrap    = $('schedule-matrix-wrap');
  const tzGroup = $('timezone-group');
  if (wrap)    { wrap.style.opacity = enabled ? '1' : '0.4'; wrap.style.pointerEvents = enabled ? '' : 'none'; }
  if (tzGroup) { tzGroup.style.opacity = enabled ? '1' : '0.4'; }
}
