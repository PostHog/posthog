/**
 * Recognizing evidence links inside agent messages.
 *
 * Agents cite the PostHog data they consulted as `[label](evidence:<kind>/<id>)`
 * links. The scheme survives `markdownUrlTransform` (like `chart:` links do) and
 * the markdown `a` component renders it as an inline evidence reference with a
 * hover preview, instead of an external link.
 *
 * The link carries only the reference. Names, status, and the open-in-PostHog
 * URL are resolved live when the reference is shown, so transcripts never
 * embed a stale copy of the data.
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

// Paths mirror PostHog's canonical route table (the `generate-app-url` MCP
// tool carries the same list). Feature flag pages only resolve by numeric id,
// so a flag cited by key gets no direct URL.
const KIND_WEB_PATH: Record<
  string,
  (encodedId: string, rawId: string) => string | null
> = {
  insight: (id) => `/insights/${id}`,
  dashboard: (id) => `/dashboard/${id}`,
  error: (id) => `/error_tracking/${id}`,
  replay: (id) => `/replay/${id}`,
  flag: (id, raw) => (/^\d+$/.test(raw) ? `/feature_flags/${id}` : null),
  experiment: (id) => `/experiments/${id}`,
  survey: (id) => `/surveys/${id}`,
  ticket: (id) => `/support/tickets/${id}`,
  trace: (id) => `/ai-observability/traces/${id}`,
  eval: (id) => `/ai-evals/evaluations/${id}`,
  cohort: (id) => `/cohorts/${id}`,
  action: (id) => `/data-management/actions/${id}`,
  person: (id) => `/persons/${id}`,
};

/**
 * Project-relative PostHog web path for an evidence target, or null when the
 * kind has no canonical page to open.
 */
export function evidenceWebPath(kind: string, id: string): string | null {
  const build = KIND_WEB_PATH[kind];
  return build ? build(encodeURIComponent(id), id) : null;
}
