import { type StoreApi, useStore } from "zustand";

type WithSelectors<S> = S extends { getState: () => infer T }
  ? S & { use: { [K in keyof T]: () => T[K] } }
  : never;

// UI-layer helper: attaches `.use.<field>()` selector hooks to a vanilla
// `StoreApi` (e.g. a core-owned store). React lives here, never in core.
// Idempotent — safe to apply once to a singleton store at module load.
export function createSelectors<S extends StoreApi<object>>(_store: S) {
  const store = _store as WithSelectors<S>;
  if (!store.use) {
    store.use = {} as WithSelectors<S>["use"];
    for (const k of Object.keys(store.getState())) {
      (store.use as Record<string, () => unknown>)[k] = () =>
        useStore(_store, (s) => s[k as keyof typeof s]);
    }
  }
  return store;
}
