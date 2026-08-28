import { resolveService } from "@posthog/di/container";
import {
  SHELL_CLIENT,
  type ShellClient,
} from "@posthog/ui/features/terminal/shellClient";
import { logger } from "@posthog/ui/shell/logger";
import { terminalManager } from "./TerminalManager";
import { useTerminalStore } from "./terminalStore";

const log = logger.scope("destroy-shell-terminal");

// Standalone terminals have no task/workspace teardown to kill their pty, so
// removal must destroy the server-side session explicitly. It must also drop
// the renderer instance: the manager keeps an exited instance, and a later
// terminal with the same session id would attach to it instead of starting.
export function destroyTerminalSession(
  sessionId: string,
  stateKey: string = sessionId,
): void {
  terminalManager.destroy(sessionId);
  useTerminalStore.getState().clearTerminalState(stateKey);
  resolveService<ShellClient>(SHELL_CLIENT)
    .destroy({ sessionId })
    .catch((error: Error) => {
      log.error("Failed to destroy shell session:", sessionId, error);
    });
}

export function destroyShellTerminal(stateKey: string): void {
  const sessionId =
    useTerminalStore.getState().terminalStates[stateKey]?.sessionId;
  if (sessionId) {
    destroyTerminalSession(sessionId, stateKey);
    return;
  }
  useTerminalStore.getState().clearTerminalState(stateKey);
}
