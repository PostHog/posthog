/**
 * The internal spec for full-size chart cards in agent messages.
 *
 * Agents author charts as block-display object tags (see remarkObjectTags):
 *
 *   <insight id="9pQx3" display="block"/>
 *   <hogql display="block" title="DAU, last 7 days">SELECT ...</hogql>
 *
 * The plugin normalizes those into a `posthog-chart` code node whose body is
 * this JSON spec; the markdown renderer draws it as a chart card instead of
 * highlighted code. A chart is always a reference (a saved insight) or a
 * query - never inline data - so every render resolves live and transcripts
 * never store a stale copy of the numbers.
 */

/**
 * hast property remarkObjectTags stamps on the chart code nodes it generates.
 * Chart-card dispatch requires it, so only plugin-generated blocks resolve to
 * live queries: markdown text cannot set AST data, and the sanitize schemas on
 * raw-HTML surfaces strip `data-*` from `code`, so a hand-authored
 * ```posthog-chart fence or literal `<code data-posthog-chart>` stays inert.
 */
export const CHART_BLOCK_MARKER = "dataPosthogChart";

/** True when a hast `code` element carries the {@link CHART_BLOCK_MARKER}. */
export function isGeneratedChartBlock(node: unknown): boolean {
  if (typeof node !== "object" || node === null) return false;
  const properties = (node as { properties?: Record<string, unknown> })
    .properties;
  return properties?.[CHART_BLOCK_MARKER] != null;
}

const MAX_TITLE_LENGTH = 120;
const MAX_CAPTION_LENGTH = 300;
const MAX_QUERY_LENGTH = 20_000;

export type ChartBlockSpec =
  | { mode: "insight"; shortId: string; title?: string; caption?: string }
  | { mode: "hogql"; query: string; title?: string; caption?: string }
  | { mode: "replay"; sessionId: string; title?: string; caption?: string };

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function capText(value: unknown, max: number): string | undefined {
  return typeof value === "string" && value.trim()
    ? value.trim().slice(0, max)
    : undefined;
}

/** Stable identity for a block: keys React elements and the query cache. */
export function chartBlockKey(source: string): string {
  let hash = 5381;
  for (let i = 0; i < source.length; i++) {
    hash = ((hash << 5) + hash + source.charCodeAt(i)) | 0;
  }
  return `chart-block-${(hash >>> 0).toString(36)}`;
}

/** Parse a `posthog-chart` node body into a spec, or null when malformed. */
export function parseChartBlock(source: string): ChartBlockSpec | null {
  let raw: unknown;
  try {
    raw = JSON.parse(source);
  } catch {
    return null;
  }
  if (!isRecord(raw)) return null;

  const title = capText(raw.title, MAX_TITLE_LENGTH);
  const caption = capText(raw.caption, MAX_CAPTION_LENGTH);

  if (raw.mode === "insight") {
    const shortId = capText(raw.shortId, 64);
    return shortId ? { mode: "insight", shortId, title, caption } : null;
  }
  if (raw.mode === "hogql") {
    const query = capText(raw.query, MAX_QUERY_LENGTH);
    return query ? { mode: "hogql", query, title, caption } : null;
  }
  if (raw.mode === "replay") {
    const sessionId = capText(raw.sessionId, 200);
    return sessionId ? { mode: "replay", sessionId, title, caption } : null;
  }
  return null;
}
