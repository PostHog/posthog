// Catches: regressions in flag serving basics — initial provider values, fallbacks for unknown flags, and manual refresh applying new values.
import test from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const { createFlagCache } = require("../src/flags.js");

function makeFakeProvider(initial) {
  const state = { flags: { ...initial } };
  return {
    state,
    provider: {
      async fetchFlags() {
        return { ...state.flags };
      },
    },
  };
}

test("first read serves the provider's values", async () => {
  const { provider } = makeFakeProvider({ promo_banner: true, maintenance_mode: false });
  const cache = createFlagCache(provider, { ttlMs: 30_000 });
  assert.equal(await cache.getFlag("promo_banner", false), true);
  assert.equal(await cache.getFlag("maintenance_mode", true), false);
});

test("unknown flags fall back to the provided default", async () => {
  const { provider } = makeFakeProvider({ promo_banner: true });
  const cache = createFlagCache(provider, { ttlMs: 30_000 });
  assert.equal(await cache.getFlag("does_not_exist", false), false);
  assert.equal(await cache.getFlag("does_not_exist", true), true);
});

test("manual refresh applies new provider values immediately", async () => {
  const { state, provider } = makeFakeProvider({ promo_banner: true });
  const cache = createFlagCache(provider, { ttlMs: 30_000 });
  assert.equal(await cache.getFlag("promo_banner", false), true);
  state.flags.promo_banner = false;
  await cache.refresh();
  assert.equal(await cache.getFlag("promo_banner", true), false);
});
