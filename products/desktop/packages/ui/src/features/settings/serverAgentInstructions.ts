export type InstructionsMoveStep = "wait" | "upload" | "done";

/**
 * What to do with the local custom instructions for one project. Instructions
 * already on the server win, so this never overwrites them.
 */
export function nextInstructionsMoveStep(input: {
  localReady: boolean;
  local: string;
  server: string;
}): InstructionsMoveStep {
  if (!input.localReady) return "wait";
  if (input.server.trim() || !input.local.trim()) return "done";
  return "upload";
}

/** Cloud tasks carry a local copy only until the server holds the instructions. */
export function cloudTaskCarriesLocalInstructions(input: {
  flagEnabled: boolean;
  projectId: number | null;
  onServerProjectIds: readonly number[];
}): boolean {
  return !(
    input.flagEnabled &&
    input.projectId != null &&
    input.onServerProjectIds.includes(input.projectId)
  );
}
