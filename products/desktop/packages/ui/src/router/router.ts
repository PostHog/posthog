import {
  createHashHistory,
  createRouter as createTanStackRouter,
} from "@tanstack/react-router";
import { RouteNotFound } from "./RouteNotFound";
import { RoutePending } from "./RoutePending";
import { setRouter } from "./routerRef";
import { routeTree } from "./routeTree.gen";

export const router = createTanStackRouter({
  routeTree,
  history: createHashHistory(),
  defaultPreload: "intent",
  // Preloads only warm code imports — never satisfy a navigation's loader.
  // Loaders here are single-frame yields (see yieldToPaint) whose whole point
  // is to run ON navigation so the pending skeleton paints; a hover-preloaded
  // loader result would let the navigation commit synchronously and freeze the
  // old screen through the destination's heavy mount again.
  defaultPreloadStaleTime: 0,
  // Show the route's pending UI the instant its loader is still resolving, so
  // navigation commits immediately instead of stalling on the previous screen.
  defaultPendingMs: 0,
  // Don't hold the pending UI for the default 500ms minimum — skeletons paint
  // for exactly the frame(s) a `yieldToPaint()` loader needs, then the real
  // view replaces them as soon as it has rendered.
  defaultPendingMinMs: 0,
  defaultPendingComponent: RoutePending,
  defaultNotFoundComponent: RouteNotFound,
  scrollRestoration: false,
});

// Publish the instance to the leaf ref so imperative callers reach it without a
// static import of this module (which would re-create the route-tree cycle).
setRouter(router);

declare module "@tanstack/react-router" {
  interface Register {
    router: typeof router;
  }
}
