/** The server limit for "My instructions". */
export const MAX_SERVER_AGENT_INSTRUCTIONS_LENGTH = 20_000;

export type InstructionsMove =
  | { step: "wait" }
  | { step: "done" }
  | { step: "keepLocal" }
  | { step: "upload"; instructions: string };

/**
 * What to do with the local custom instructions for one project. The result
 * keeps every instruction: text already on the server stays first, and the
 * local text follows it unless the server text already contains it.
 */
export function nextInstructionsMove(input: {
  localReady: boolean;
  local: string;
  server: string;
}): InstructionsMove {
  if (!input.localReady) return { step: "wait" };
  const local = input.local.trim();
  const server = input.server.trim();
  if (!local || server.includes(local)) return { step: "done" };
  const instructions = server ? `${server}\n\n${local}` : local;
  // Too long for the server: keep sending the local copy so nothing is lost.
  if (instructions.length > MAX_SERVER_AGENT_INSTRUCTIONS_LENGTH) {
    return { step: "keepLocal" };
  }
  return { step: "upload", instructions };
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
