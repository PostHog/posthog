// Catches: flag values cached at first read with no TTL — provider-side toggles (e.g. a kill-switch) never reaching served values until process restart.
import test from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const { createFlagCache } = require("../src/flags.js");

function makeFakeProvider(initial) {
  const state = { flags: { ...initial }, fetchCount: 0 };
  return {
    state,
    provider: {
      async fetchFlags() {
        state.fetchCount += 1;
        return { ...state.flags };
      },
    },
  };
}

test("a toggled kill-switch is served once the TTL elapses", async () => {
  const { state, provider } = makeFakeProvider({ promo_banner: true });
  let clock = 1_000_000;
  const cache = createFlagCache(provider, { ttlMs: 30_000, now: () => clock });

  assert.equal(await cache.getFlag("promo_banner", false), true);

  state.flags.promo_banner = false;
  clock += 31_000;
  assert.equal(
    await cache.getFlag("promo_banner", false),
    false,
    "flag reads past the TTL must reflect the provider-side toggle"
  );
});

test("the default TTL keeps served flags no staler than 60 seconds", async () => {
  const { state, provider } = makeFakeProvider({ promo_banner: true });
  let clock = 1_000_000;
  const cache = createFlagCache(provider, { now: () => clock });

  assert.equal(await cache.getFlag("promo_banner", false), true);

  state.flags.promo_banner = false;
  clock += 61_000;
  assert.equal(await cache.getFlag("promo_banner", false), false);
});

test("flags created at the provider after startup appear once the TTL elapses", async () => {
  const { state, provider } = makeFakeProvider({ promo_banner: true });
  let clock = 1_000_000;
  const cache = createFlagCache(provider, { ttlMs: 30_000, now: () => clock });

  assert.equal(await cache.getFlag("holiday_banner", false), false);

  state.flags.holiday_banner = true;
  clock += 31_000;
  assert.equal(await cache.getFlag("holiday_banner", false), true);
});
