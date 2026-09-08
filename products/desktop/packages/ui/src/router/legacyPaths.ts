import { type ParsedLocation, redirect } from "@tanstack/react-router";

/**
 * Route prefixes that moved when the app's routes were flattened, longest
 * first so `/website/home` can never be eaten by `/website`.
 *
 * Old hrefs outlive the move: a saved startup location, a deep link, a shared
 * link, a notification, a browser-tab history entry. Both the startup restore
 * and the legacy redirect routes rewrite through this table.
 */
const MOVED_PREFIXES: readonly (readonly [string, string])[] = [
  ["/website/command-center", "/command-center"],
  ["/website/mcp-servers", "/mcp-servers"],
  ["/website/activity", "/activity"],
  ["/website/skills", "/skills"],
  ["/website/feeds", "/feeds"],
  ["/website/home", "/"],
  ["/website/new", "/new"],
  ["/website", "/spaces"],
  ["/code/inbox", "/inbox"],
  ["/code/agents", "/agents"],
  ["/code/archived", "/archived"],
  ["/code/loops", "/loops"],
  ["/code/tasks", "/tasks"],
  ["/code/pr", "/pr"],
  ["/code", "/new"],
];

const MOVED_LONGEST_FIRST = [...MOVED_PREFIXES].sort(
  (a, b) => b[0].length - a[0].length,
);

/** A path on today's routes. Unrecognized paths are returned unchanged. */
export function rewriteLegacyPath(path: string): string {
  for (const [from, to] of MOVED_LONGEST_FIRST) {
    if (path === from) return to;
    if (path.startsWith(`${from}/`)) {
      const rest = path.slice(from.length);
      return singleLeadingSlash(to === "/" ? rest : to + rest);
    }
  }
  return path;
}

/**
 * A rewritten path always names a route in this app. Doubling the leading
 * slash would make it protocol-relative (`//evil.example/x` is an origin, not
 * a path), so a crafted old link can't turn a redirect into a trip off-app.
 */
function singleLeadingSlash(path: string): string {
  return path.replace(/^\/+/, "/");
}

/**
 * The same rewrite over a whole href. A `?` or `#` sitting right at a prefix
 * boundary (`/code/pr?prUrl=…`) matches no prefix, so the href would fall
 * through to the `/code` → `/new` catch-all and land on a dead route. Match on
 * the pathname only, then reattach the suffix untouched.
 */
export function rewriteLegacyHref(href: string): string {
  const boundary = href.search(/[?#]/);
  if (boundary === -1) return rewriteLegacyPath(href);
  return rewriteLegacyPath(href.slice(0, boundary)) + href.slice(boundary);
}

/**
 * Send an old URL to where its page lives now, keeping any search and hash.
 * Replaces rather than pushes, so Back skips the route that no longer exists.
 */
export function redirectFromLegacyPath(location: ParsedLocation): never {
  throw redirect({
    href:
      rewriteLegacyPath(location.pathname) +
      location.searchStr +
      (location.hash ? `#${location.hash}` : ""),
    replace: true,
  });
}
