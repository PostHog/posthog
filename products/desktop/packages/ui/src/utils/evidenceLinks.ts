import { getObjectKind } from "./objectKinds";

/**
 * The internal `evidence:<kind>/<id>` href form for object references inside
 * agent messages. Agents author references as `<kind id="...">` tags (see
 * remarkObjectTags), which normalize to link nodes with this scheme; the
 * scheme survives `markdownUrlTransform` (like `chart:` links do) and the
 * markdown `a` component renders it as an inline reference chip.
 *
 * The reference carries no data. Names, status, and the open-in-PostHog URL
 * are resolved live when the reference is shown, so transcripts never embed
 * a stale copy of the data. For `hogql` references the id is the SQL itself.
 */

const EVIDENCE_SCHEME = "evidence:";
const KIND_ID_RE = /^([a-z][a-z0-9-]*)\/([^/?#]+)$/;

export interface EvidenceLinkTarget {
  /** Free-form kind slug; well-known kinds get a dedicated icon and source label. */
  kind: string;
  id: string;
}

function decodePart(part: string): string {
  try {
    return decodeURIComponent(part);
  } catch {
    return part;
  }
}

/**
 * Parse an `evidence:` href into a target, or null when it isn't one.
 * A query string is tolerated and ignored: earlier links carried display
 * params, and the reference alone identifies the object.
 */
export function parseEvidenceLink(
  href: string | undefined,
): EvidenceLinkTarget | null {
  if (!href || !href.startsWith(EVIDENCE_SCHEME)) return null;

  const rest = href.slice(EVIDENCE_SCHEME.length);
  const queryIndex = rest.indexOf("?");
  const path = queryIndex === -1 ? rest : rest.slice(0, queryIndex);

  const match = KIND_ID_RE.exec(path);
  if (!match) return null;

  return { kind: match[1], id: decodePart(match[2]) };
}

/**
 * Project-relative PostHog web path for an evidence target, or null when the
 * kind has no canonical page to open. Paths come from the kind registry.
 */
export function evidenceWebPath(kind: string, id: string): string | null {
  const build = getObjectKind(kind).webPath;
  return build ? build(encodeURIComponent(id), id) : null;
}
