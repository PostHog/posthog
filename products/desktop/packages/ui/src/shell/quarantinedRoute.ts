/**
 * The route the host stopped loading because the renderer crashed on it more
 * than once. It arrives as a query parameter on the app's own URL, and is
 * cleared as it is read so a later reload does not report it a second time.
 */
export function takeQuarantinedRoute(): string | null {
  const url = new URL(window.location.href);
  const route = url.searchParams.get("quarantinedRoute");
  if (!route) return null;
  url.searchParams.delete("quarantinedRoute");
  window.history.replaceState(window.history.state, "", url.toString());
  return route;
}

/** The task a quarantined route points at, when it points at one. */
export function quarantinedTaskId(route: string): string | null {
  return /\/tasks\/([^/?#]+)/.exec(route)?.[1] ?? null;
}
