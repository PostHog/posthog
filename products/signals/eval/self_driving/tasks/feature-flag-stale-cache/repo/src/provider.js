const DEFAULT_FLAGS = { promo_banner: true, maintenance_mode: false, new_nav: false };

/** Reads flag values from the hosted flag service, falling back to shipped defaults. */
function createProvider({ url = process.env.FLAGS_SERVICE_URL, fetchImpl = fetch } = {}) {
  return {
    async fetchFlags() {
      if (!url) return { ...DEFAULT_FLAGS };
      const response = await fetchImpl(url, { headers: { accept: "application/json" } });
      if (!response.ok) throw new Error(`Flag service responded ${response.status}`);
      return { ...DEFAULT_FLAGS, ...(await response.json()) };
    },
  };
}

module.exports = { createProvider, DEFAULT_FLAGS };
