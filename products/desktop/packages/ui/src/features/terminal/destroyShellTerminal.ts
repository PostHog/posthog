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
// removal must destroy the server-side session explicitly.
export function destroyShellTerminal(stateKey: string): void {
  const sessionId =
    useTerminalStore.getState().terminalStates[stateKey]?.sessionId;
  if (sessionId) {
    terminalManager.destroy(sessionId);
    resolveService<ShellClient>(SHELL_CLIENT)
      .destroy({ sessionId })
      .catch((error: Error) => {
        log.error("Failed to destroy shell session:", sessionId, error);
      });
  }
  useTerminalStore.getState().clearTerminalState(stateKey);
}
