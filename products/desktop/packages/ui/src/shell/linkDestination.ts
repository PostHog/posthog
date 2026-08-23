// URL-resolution rules for the LinkDestinationBar (the browser-style status
// bar). Kept apart from the component file so it exports only components.

// Any href carrying an explicit scheme, e.g. "https:", "mailto:",
// "posthog-code:".
const SCHEME_RE = /^[a-z][a-z0-9+.-]*:/i;

// Schemes whose href is executable or opaque rather than a destination a
// person could recognize. `evidence:` is the internal chip scheme with its own
// hover preview (see EvidenceRefChip).
const HIDDEN_SCHEMES = new Set(["javascript:", "evidence:", "data:", "blob:"]);

/**
 * The destination to preview for a hovered/focused element, or null when there
 * is nothing worth showing.
 *
 * Anchors with an absolute URL show as-is. Relative hrefs are in-app router
 * links whose path is an implementation detail, so they stay quiet. Non-anchor
 * controls that open a URL onClick can opt in with
 * `data-link-destination="<url>"`; an anchor can suppress its preview with
 * `data-link-destination=""`.
 */
export function resolveLinkDestination(
  target: EventTarget | null,
): string | null {
  if (!(target instanceof Element)) return null;
  const el = target.closest("a[href], [data-link-destination]");
  if (!el) return null;
  const override = el.getAttribute("data-link-destination");
  if (override !== null) {
    const trimmed = override.trim();
    return trimmed === "" ? null : trimmed;
  }
  const href = el.getAttribute("href")?.trim();
  if (!href) return null;
  const scheme = SCHEME_RE.exec(href)?.[0].toLowerCase();
  if (!scheme || HIDDEN_SCHEMES.has(scheme)) return null;
  return href;
}
