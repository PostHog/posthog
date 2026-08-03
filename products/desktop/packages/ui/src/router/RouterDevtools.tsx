import { lazy, Suspense } from "react";
import { router } from "./router";

// The genuine floating TanStack Router devtools overlay (drawer, drag-to-resize,
// in-panel close button, open animation — the exact UI), but with its floating
// TanStack logo hidden so the dev toolbar owns the trigger instead. It receives
// the app `router` explicitly because it is mounted as a sibling of the
// RouterProvider, so it is outside the router's React context.
//
// Dynamic import behind an `import.meta.env.DEV` gate keeps the devtools chunk
// out of the production bundle: the constant folds at build time, so the branch
// (and its import target) is eliminated from prod builds entirely.

// The overlay has no controlled-open API and its internal open signal does not
// react to external localStorage writes, so the toolbar drives it by clicking
// its own elements: the hidden logo opens it, its in-panel close button closes
// it. Both keep this localStorage key in sync, which is how we read open state.
const OPEN_STORAGE_KEY = "tanstackRouterDevtoolsOpen";
const ROOT_ID = "tanstack-router-devtools-root";
const TOGGLE_ID = "tanstack-router-devtools-toggle";

export function isRouterDevtoolsOpen(): boolean {
  try {
    return (
      JSON.parse(localStorage.getItem(OPEN_STORAGE_KEY) ?? "false") === true
    );
  } catch {
    return false;
  }
}

// Returns the new open state so the caller can reflect it immediately.
export function toggleRouterDevtools(): boolean {
  const root = document.getElementById(ROOT_ID);
  if (!root) return false;
  if (isRouterDevtoolsOpen()) {
    // The panel's own close button is the chevron-down (viewBox "0 0 10 6").
    const closeButton =
      root
        .querySelector<SVGElement>('svg[viewBox="0 0 10 6"]')
        ?.closest("button") ?? null;
    closeButton?.click();
    return false;
  }
  document.getElementById(TOGGLE_ID)?.click();
  return true;
}

const LazyRouterDevtools = import.meta.env.DEV
  ? lazy(async () => {
      const { TanStackRouterDevtools } = await import(
        "@tanstack/react-router-devtools"
      );
      return {
        default: () => (
          <TanStackRouterDevtools
            router={router}
            toggleButtonProps={{ id: TOGGLE_ID, style: { display: "none" } }}
          />
        ),
      };
    })
  : () => null;

export function RouterDevtools() {
  return (
    <div id={ROOT_ID}>
      <Suspense fallback={null}>
        <LazyRouterDevtools />
      </Suspense>
    </div>
  );
}
