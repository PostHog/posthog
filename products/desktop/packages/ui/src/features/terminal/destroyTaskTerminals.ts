import { terminalManager } from "./TerminalManager";
import { useTerminalStore } from "./terminalStore";

export function destroyTaskTerminals(taskId: string): void {
  terminalManager.destroyForTask(taskId);
  useTerminalStore.getState().clearTerminalStatesForTask(taskId);
}
