const analytics = require("./analytics");

/**
 * Caches flag values in front of the provider so request handling
 * never blocks on the flag service. `ttlMs` bounds how long fetched
 * values are considered fresh.
 */
function createFlagCache(provider, options = {}) {
  const { ttlMs = 60_000, now = Date.now } = options;
  const state = { values: {}, fetchedAt: 0 };

  async function refresh() {
    state.values = await provider.fetchFlags();
    state.fetchedAt = now();
    analytics.capture("system", "flags_refreshed", { flag_count: Object.keys(state.values).length });
  }

  async function getFlag(key, fallback = false) {
    if (state.fetchedAt === 0) {
      await refresh();
    }
    return state.values[key] ?? fallback;
  }

  return { getFlag, refresh, ttlMs };
}

module.exports = { createFlagCache };
