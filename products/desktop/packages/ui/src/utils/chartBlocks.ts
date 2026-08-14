/**
 * Recognizing chart blocks inside agent messages.
 *
 * Where an `evidence:` link is an inline citation, a chart block is the
 * full-size variant: agents emit a fenced code block tagged `posthog-chart`
 * whose body is a JSON spec, and the markdown renderer draws it as a chart
 * card instead of highlighted code.
 *
 * Two payload shapes:
 *
 * Inline data the agent already has (drawn with no fetching):
 * ```posthog-chart
 * { "title": "Daily active users", "render": "bar",
 *   "labels": ["Aug 7", "Aug 8"], "series": [{ "name": "DAU", "points": [69650, 39431] }] }
 * ```
 *
 * A PostHog query node (executed via `/query/`, like report charts):
 * ```posthog-chart
 * { "title": "Daily active users", "query": { "kind": "InsightVizNode", "source": { "kind": "TrendsQuery", ... } } }
 * ```
 */

const MAX_POINTS = 366;
const MAX_SERIES = 15;
const MAX_TITLE_LENGTH = 120;
const MAX_CAPTION_LENGTH = 300;

export interface ChartBlockSeries {
  name: string;
  points: number[];
}

export type ChartBlockSpec =
  | {
      mode: "data";
      title?: string;
      caption?: string;
      render: "line" | "bar";
      labels: string[];
      series: ChartBlockSeries[];
    }
  | {
      mode: "query";
      title?: string;
      caption?: string;
      query: Record<string, unknown>;
    };

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function capText(value: unknown, max: number): string | undefined {
  return typeof value === "string" && value.trim()
    ? value.trim().slice(0, max)
    : undefined;
}

function toSeries(raw: unknown): ChartBlockSeries[] | null {
  if (!Array.isArray(raw)) return null;
  const series: ChartBlockSeries[] = [];
  for (const entry of raw.slice(0, MAX_SERIES)) {
    if (!isRecord(entry) || !Array.isArray(entry.points)) continue;
    const points = entry.points.slice(0, MAX_POINTS).map(Number);
    if (points.length === 0 || !points.every(Number.isFinite)) continue;
    series.push({
      name:
        typeof entry.name === "string" && entry.name
          ? entry.name
          : `Series ${series.length + 1}`,
      points,
    });
  }
  return series.length > 0 ? series : null;
}

/** Stable identity for a block: keys React elements and the query cache. */
export function chartBlockKey(source: string): string {
  let hash = 5381;
  for (let i = 0; i < source.length; i++) {
    hash = ((hash << 5) + hash + source.charCodeAt(i)) | 0;
  }
  return `chart-block-${(hash >>> 0).toString(36)}`;
}

/** Parse a `posthog-chart` fence body into a spec, or null when malformed. */
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

  if (isRecord(raw.query)) {
    // The query node itself stays untrusted JSON: planReportChart decides
    // whether it is runnable, links out, or is dropped.
    return { mode: "query", title, caption, query: raw.query };
  }

  const series = toSeries(raw.series);
  if (!series) return null;
  const labels = Array.isArray(raw.labels)
    ? raw.labels.slice(0, MAX_POINTS).map(String)
    : [];
  return {
    mode: "data",
    title,
    caption,
    render: raw.render === "bar" ? "bar" : "line",
    labels,
    series,
  };
}
