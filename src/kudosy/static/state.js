// ── Kudosy UI — state.js ─────────────────────────────────────────────────────
// Shared mutable state — exported as a single object so all modules can
// mutate it in-place.  ES module named exports of primitive let-bindings
// are live but cannot be reassigned by importers; an object sidesteps that.

export const state = {
  // Sport data (loaded once at startup by main.js)
  sportTypes: [],
  sportCategories: {},   // { FootSports: [...], CycleSports: [...], … }

  // Athlete cache (populated by loadConfig and athlete search)
  athleteLabels: {},
  athleteAvatars: {},

  // Feed data
  feedActivities: [],
  feedFetchedAt: null,
  feedLoaded: false,   // true after the first successful feed fetch
  statsLoaded: false,  // true after the first stats tab visit
  feedFilter: { status: 'all', text: '', sport: '' },

  // Log-tab polling timer
  pollTimer: null,
  // Live-log EventSource (null = not connected → fall back to polling)
  logStream: null,

  // Run-button spinner state
  // The button whose spinner is currently active (null when idle).
  runningButton: null,
  // finished_at that was current when the user clicked Run — cleared by
  // pollStatus() once a *newer* finished_at appears.
  runStartStamp: null,
  // Updated every pollStatus() tick so startRun() can snapshot it.
  currentLastRunStamp: null,

  // Auto-save guard — kept false during init so that loadConfig /
  // loadSettings DOM mutations don't trigger premature API calls.
  // main.js sets this to true after both loads complete.
  autoSaveEnabled: false,
};
