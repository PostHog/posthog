import { logger } from "@posthog/ui/shell/logger";

const log = logger.scope("renderer");

/** A tight error loop must not turn the host log into a firehose. */
const MAX_LINES_PER_MINUTE = 20;

function describeReason(reason: unknown): { message: string; stack?: string } {
  if (reason instanceof Error) {
    return {
      message: `${reason.name}: ${reason.message}`,
      stack: reason.stack,
    };
  }
  if (typeof reason === "string") return { message: reason };
  try {
    return { message: JSON.stringify(reason) ?? String(reason) };
  } catch {
    return { message: String(reason) };
  }
}

/**
 * Mirrors uncaught renderer errors and unhandled rejections into the host log,
 * next to the session lifecycle lines they may explain. Error tracking already
 * receives them; the host log is what a user can hand over from a machine.
 */
export function installUncaughtErrorLogging(): () => void {
  let windowStartedAt = Date.now();
  let linesThisWindow = 0;

  const allow = (): boolean => {
    const now = Date.now();
    if (now - windowStartedAt >= 60_000) {
      windowStartedAt = now;
      linesThisWindow = 0;
    }
    linesThisWindow += 1;
    return linesThisWindow <= MAX_LINES_PER_MINUTE;
  };

  const onError = (event: ErrorEvent): void => {
    if (!allow()) return;
    log.error("Uncaught renderer error", {
      message: event.message,
      source: `${event.filename}:${event.lineno}:${event.colno}`,
      stack: event.error instanceof Error ? event.error.stack : undefined,
    });
  };
  const onRejection = (event: PromiseRejectionEvent): void => {
    if (!allow()) return;
    log.error("Unhandled renderer rejection", describeReason(event.reason));
  };

  window.addEventListener("error", onError);
  window.addEventListener("unhandledrejection", onRejection);
  return () => {
    window.removeEventListener("error", onError);
    window.removeEventListener("unhandledrejection", onRejection);
  };
}
