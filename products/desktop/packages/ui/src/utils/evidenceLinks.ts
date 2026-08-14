/**
 * Recognizing evidence links inside agent messages.
 *
 * Agents cite the PostHog data they consulted as `[label](evidence:<kind>/<id>)`
 * links. The scheme survives `markdownUrlTransform` (like `chart:` links do) and
 * the markdown `a` component renders it as an inline evidence reference with a
 * hover preview, instead of an external link.
 *
 * Optional query parameters enrich the reference without any data fetching:
 * - `url`: PostHog web URL of the object, makes the reference clickable.
 * - `value`: headline figure for the hover card, e.g. `28.1%`.
 * - `desc`: one context line for the hover card, e.g. `down 12.9pts since Jan 3`.
 * - `series`: comma-separated numbers the agent already has, drawn as a
 *   sparkline on the hover card, e.g. `41,39,40,28,27`.
 *
 * `evidence:insight/9pQx3?url=https%3A%2F%2Fus.posthog.com%2F...&value=28.1%25&desc=down+12.9pts`
 */

const EVIDENCE_SCHEME = "evidence:";
const KIND_ID_RE = /^([a-z][a-z0-9-]*)\/([^/?#]+)$/;

export interface EvidenceLinkTarget {
  /** Free-form kind slug; well-known kinds get a dedicated icon and source label. */
  kind: string;
  id: string;
  /** PostHog web URL of the underlying object, when the agent included one. */
  url?: string;
  /** Headline figure for the hover card, e.g. "28.1%". */
  value?: string;
  /** One context line for the hover card. */
  desc?: string;
  /** Data points for the hover-card sparkline, oldest first. */
  series?: number[];
}

// Display params are agent-written text headed for a small card; caps keep a
// runaway link from flooding the layout.
const MAX_VALUE_LENGTH = 40;
const MAX_DESC_LENGTH = 160;
const MAX_SERIES_POINTS = 60;

/** A sparkline needs 2+ finite numbers; anything else is dropped whole. */
function parseSeriesParam(raw: string): number[] | null {
  const parts = raw.split(",").slice(0, MAX_SERIES_POINTS);
  if (parts.length < 2) return null;
  const points = parts.map((part) => Number(part.trim()));
  return points.every(Number.isFinite) ? points : null;
}

function decodePart(part: string): string {
  try {
    return decodeURIComponent(part);
  } catch {
    return part;
  }
}

/** Parse an `evidence:` href into a target, or null when it isn't one. */
export function parseEvidenceLink(
  href: string | undefined,
): EvidenceLinkTarget | null {
  if (!href || !href.startsWith(EVIDENCE_SCHEME)) return null;

  const rest = href.slice(EVIDENCE_SCHEME.length);
  const queryIndex = rest.indexOf("?");
  const path = queryIndex === -1 ? rest : rest.slice(0, queryIndex);
  const query = queryIndex === -1 ? "" : rest.slice(queryIndex + 1);

  const match = KIND_ID_RE.exec(path);
  if (!match) return null;

  const target: EvidenceLinkTarget = {
    kind: match[1],
    id: decodePart(match[2]),
  };

  if (query) {
    const params = new URLSearchParams(query);
    const url = params.get("url");
    if (url && (url.startsWith("https://") || url.startsWith("http://"))) {
      target.url = url;
    }
    const value = params.get("value")?.trim();
    if (value) target.value = value.slice(0, MAX_VALUE_LENGTH);
    const desc = params.get("desc")?.trim();
    if (desc) target.desc = desc.slice(0, MAX_DESC_LENGTH);
    const series = params.get("series");
    if (series) {
      const points = parseSeriesParam(series);
      if (points) target.series = points;
    }
  }

  return target;
}
