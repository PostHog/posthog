import { resolveService } from "@posthog/di/container";
import { recordLog } from "./logCapture";

export interface ScopedLogger {
  info(...args: unknown[]): void;
  warn(...args: unknown[]): void;
  error(...args: unknown[]): void;
  debug(...args: unknown[]): void;
}

export interface HostLogger extends ScopedLogger {
  scope(name: string): ScopedLogger;
}

export const HOST_LOGGER = Symbol.for("posthog.ui.HostLogger");

function impl(): HostLogger | null {
  try {
    return resolveService<HostLogger>(HOST_LOGGER);
  } catch {
    return null;
  }
}

// Every log line is also teed into the in-memory capture buffer
// (shell/logCapture) so error surfaces can bundle recent logs — even on hosts
// that bind no HOST_LOGGER at all.
type Level = "debug" | "info" | "warn" | "error";

function emit(level: Level, scope: string | null, args: unknown[]): void {
  recordLog(level, scope, args);
  const target = impl();
  if (!target) return;
  const sink = scope ? target.scope(scope) : target;
  sink[level](...args);
}

function deferredScope(name: string): ScopedLogger {
  return {
    info: (...args) => emit("info", name, args),
    warn: (...args) => emit("warn", name, args),
    error: (...args) => emit("error", name, args),
    debug: (...args) => emit("debug", name, args),
  };
}

export const logger: HostLogger = {
  scope: (name) => deferredScope(name),
  info: (...args) => emit("info", null, args),
  warn: (...args) => emit("warn", null, args),
  error: (...args) => emit("error", null, args),
  debug: (...args) => emit("debug", null, args),
};
