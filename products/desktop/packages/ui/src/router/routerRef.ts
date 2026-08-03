// Leaf module holding the live router singleton so imperative callers
// (navigationBridge, deep-link handlers, store actions) can reach the router
// WITHOUT a static `import { router } from "./router"`.
//
// That static import creates a cycle:
//   router.ts → routeTree.gen.ts → __root.tsx → hooks → navigationBridge → router.ts
// Under `autoCodeSplitting` each route's component becomes its own module that
// re-enters the cycle, and the TDZ ("Cannot access 'rootRouteImport' before
// initialization") leaves code-split route chunks stuck loading.
//
// The `import type` below is erased at build time, so this module has no runtime
// imports and cannot participate in the cycle.
import type { router as RouterInstance } from "./router";

let routerInstance: typeof RouterInstance | null = null;

export function setRouter(instance: typeof RouterInstance): void {
  routerInstance = instance;
}

export function getRouter(): typeof RouterInstance {
  if (!routerInstance) {
    throw new Error("Router accessed before initialization");
  }
  return routerInstance;
}

// Nullable accessor for imperative navigation helpers that must not throw when
// the router isn't mounted yet (early boot, unit tests). In the running app the
// instance is always set before these fire; callers treat null as "no router,
// nothing to navigate".
export function getRouterOrNull(): typeof RouterInstance | null {
  return routerInstance;
}
