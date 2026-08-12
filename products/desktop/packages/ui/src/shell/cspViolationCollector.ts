import { logger } from "./logger";

const log = logger.scope("csp-reporting");

/**
 * postMessage method a sandboxed frame uses to hand out a CSP violation.
 * Namespaced under `posthog/` so it never collides with the MCP Apps
 * `ui/notifications/*` methods the same channel carries.
 */
export const CSP_VIOLATION_NOTIFICATION = "posthog/notifications/csp-violation";

/**
 * One entry of a Reporting API `application/reports+json` bundle, as produced by
 * `ReportingObserver`. Only the fields used for deduping are named: the rest go
 * to PostHog untouched, where the endpoint reads what it knows and keeps the
 * raw report.
 *
 * @see https://developer.mozilla.org/en-US/docs/Web/API/CSPViolationReportBody
 */
export interface CspViolationReport {
  type: "csp-violation";
  url?: string;
  body: {
    documentURL?: string;
    blockedURL?: string | null;
    effectiveDirective?: string;
    [key: string]: unknown;
  };
}

/**
 * A frame that violates its policy once usually violates it many times — every
 * blocked asset, every retry. Distinct reports are worth sending; repeats are
 * not, and not without limit.
 */
const MAX_DISTINCT_REPORTS = 50;

function asViolationReport(data: unknown): CspViolationReport | null {
  if (typeof data !== "object" || data === null) return null;
  const message = data as { method?: unknown; params?: unknown };
  if (message.method !== CSP_VIOLATION_NOTIFICATION) return null;

  const report = (message.params as { report?: unknown } | undefined)?.report;
  if (typeof report !== "object" || report === null) return null;
  const candidate = report as CspViolationReport;
  if (candidate.type !== "csp-violation") return null;
  if (typeof candidate.body !== "object" || candidate.body === null)
    return null;
  return candidate;
}

/**
 * Listens for CSP violations posted out of sandboxed frames (MCP apps, artifact
 * previews) and hands each new one to `send`.
 *
 * Returns a disposer.
 */
export function startCspViolationCollector(
  send: (report: CspViolationReport) => void,
  maxDistinctReports = MAX_DISTINCT_REPORTS,
): () => void {
  const seen = new Set<string>();
  let capReported = false;

  const onMessage = (event: MessageEvent): void => {
    const report = asViolationReport(event.data);
    if (!report) return;

    const { documentURL, effectiveDirective, blockedURL } = report.body;
    const key = `${documentURL ?? ""}|${effectiveDirective ?? ""}|${blockedURL ?? ""}`;
    if (seen.has(key)) return;

    if (seen.size >= maxDistinctReports) {
      if (!capReported) {
        capReported = true;
        log.warn(
          `Reached the cap of ${maxDistinctReports} distinct CSP violations; further ones are dropped`,
        );
      }
      return;
    }

    seen.add(key);
    log.warn("CSP violation in sandboxed frame", {
      blockedURL,
      effectiveDirective,
    });
    send(report);
  };

  window.addEventListener("message", onMessage);
  return () => window.removeEventListener("message", onMessage);
}
