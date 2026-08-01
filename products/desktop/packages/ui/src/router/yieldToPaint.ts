/**
 * Route-loader helper that resolves just after the next frame paints.
 *
 * Mounting a heavy view (task detail with its chat thread + terminal, a canvas
 * grid) blocks the main thread for hundreds of ms. Without a pending state the
 * router commits synchronously and the OLD route stays frozen on screen for
 * that whole block — a tab click looks ignored for up to a second. Awaiting
 * this in a route's `loader` keeps the navigation pending for exactly one
 * frame, which (with `pendingMs: 0`) lets the router commit the URL and paint
 * the route's skeleton `pendingComponent` BEFORE the heavy mount runs. The
 * click is acknowledged instantly; the expensive render happens behind the
 * skeleton.
 *
 * Never await anything slower than this in a loader — a network-blocked loader
 * makes the route un-navigable when the fetch hangs. Cold-miss fetches belong
 * in the component.
 */
export function yieldToPaint(): Promise<void> {
  return new Promise((resolve) => {
    // Double rAF: the first fires before the next frame paints, the second
    // before the frame after — so exactly one frame (the one showing the
    // pending skeleton) is guaranteed to reach the screen in between. A single
    // rAF can resolve before the pending state ever commits, letting the
    // router skip straight to the heavy mount with nothing painted.
    requestAnimationFrame(() => {
      requestAnimationFrame(() => setTimeout(resolve, 0));
    });
  });
}
