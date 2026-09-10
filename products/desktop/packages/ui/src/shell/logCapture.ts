// In-memory capped buffer of recent renderer log lines, teed off the shell
// logger. Exists so error surfaces (the error details dialog) can bundle the
// logs that led up to a failure without any host round trip — the host's own
// transports (file, console) are unaffected.

export interface CapturedLogEntry {
  at: number;
  level: "debug" | "info" | "warn" | "error";
  scope: string | null;
  message: string;
}

const MAX_ENTRIES = 500;

const entries: CapturedLogEntry[] = [];

// Single-line, never-throwing rendering of one log argument. Errors keep
// their stack (the whole point of capturing), objects are JSON with circular
// references elided.
function formatArg(arg: unknown): string {
  if (typeof arg === "string") return arg;
  if (arg instanceof Error) {
    return arg.stack ?? `${arg.name}: ${arg.message}`;
  }
  if (typeof arg === "object" && arg !== null) {
    const seen = new WeakSet<object>();
    try {
      return (
        JSON.stringify(arg, (_key, value: unknown) => {
          if (typeof value === "object" && value !== null) {
            if (seen.has(value)) return "[circular]";
            seen.add(value);
          }
          if (typeof value === "bigint" || typeof value === "function") {
            return String(value);
          }
          return value;
        }) ?? String(arg)
      );
    } catch {
      return String(arg);
    }
  }
  return String(arg);
}

export function recordLog(
  level: CapturedLogEntry["level"],
  scope: string | null,
  args: unknown[],
): void {
  entries.push({
    at: Date.now(),
    level,
    scope,
    message: args.map(formatArg).join(" "),
  });
  if (entries.length > MAX_ENTRIES) {
    entries.splice(0, entries.length - MAX_ENTRIES);
  }
}

// Plain-text dump of the most recent captured lines, newest last.
export function formatCapturedLogs(options?: { maxEntries?: number }): string {
  const max = options?.maxEntries ?? entries.length;
  const slice = max <= 0 ? [] : entries.slice(-max);
  if (slice.length === 0) return "(no logs captured this session)";
  return slice
    .map(
      (entry) =>
        `${new Date(entry.at).toISOString()} [${entry.level}]${
          entry.scope ? ` [${entry.scope}]` : ""
        } ${entry.message}`,
    )
    .join("\n");
}

export function clearCapturedLogs(): void {
  entries.length = 0;
}
