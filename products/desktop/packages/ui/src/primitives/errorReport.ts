export interface ErrorReportInput {
  error: Error;
  componentStack?: string | null;
  /** The `name` of the boundary that caught the error, when it has one. */
  boundaryName?: string;
  timestamp: Date;
  userAgent?: string;
}

/** One-line summary shown on the fallback screen: `TypeError: foo is not a function`. */
export function summarizeError(error: Error): string {
  const name = error.name || "Error";
  return error.message ? `${name}: ${error.message}` : name;
}

/**
 * The plain-text report the user copies and pastes into a bug report. Header
 * lines first so a reader can place it before scrolling the stack.
 */
export function buildErrorReport({
  error,
  componentStack,
  boundaryName,
  timestamp,
  userAgent,
}: ErrorReportInput): string {
  const header = [
    "PostHog Desktop error report",
    boundaryName ? `Boundary: ${boundaryName}` : null,
    `Time: ${timestamp.toISOString()}`,
    userAgent ? `User agent: ${userAgent}` : null,
  ].filter((line): line is string => line !== null);

  const sections = [
    header.join("\n"),
    error.stack || summarizeError(error),
    componentStack?.trim()
      ? `Component stack:\n${componentStack.trim()}`
      : null,
  ].filter((section): section is string => section !== null);

  return sections.join("\n\n");
}
