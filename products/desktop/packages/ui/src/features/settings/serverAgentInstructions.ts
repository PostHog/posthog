import type { SettingsStore } from "./settingsStore";

/** The server limit for "My instructions". */
export const MAX_SERVER_AGENT_INSTRUCTIONS_LENGTH = 20_000;

export type ServerInstructionsUpdate =
  | { step: "done" }
  | { step: "keepLocal" }
  | { step: "upload"; instructions: string };

/**
 * The custom instructions text without the Simplified Technical English line,
 * which stays a separate switch. Null while the AGENTS.md snapshot is loading.
 */
export function getLocalInstructionsContent(
  state: Pick<
    SettingsStore,
    | "customInstructions"
    | "syncCustomInstructionsFromFile"
    | "syncedCustomInstructions"
  >,
): string | null {
  if (!state.syncCustomInstructionsFromFile) {
    return state.customInstructions.trim();
  }
  return state.syncedCustomInstructions
    ? state.syncedCustomInstructions.content.trim()
    : null;
}

/**
 * The next "My instructions" text for one project. Desktop owns only the part
 * it uploaded: a new local text replaces that part, and any other text on the
 * server stays.
 */
export function nextServerInstructions(input: {
  server: string;
  previous: string | undefined;
  local: string;
}): ServerInstructionsUpdate {
  const server = input.server.trim();
  const previous = input.previous?.trim() ?? "";
  const local = input.local.trim();
  let next: string;
  if (previous && server.includes(previous)) {
    next = server
      .replace(previous, () => local)
      .replace(/\n{3,}/g, "\n\n")
      .trim();
  } else if (!local || server.includes(local)) {
    next = server;
  } else {
    next = server ? `${server}\n\n${local}` : local;
  }
  if (next === server) return { step: "done" };
  // Too long for the server: keep sending the local copy so nothing is lost.
  if (next.length > MAX_SERVER_AGENT_INSTRUCTIONS_LENGTH) {
    return { step: "keepLocal" };
  }
  return { step: "upload", instructions: next };
}

/**
 * Cloud tasks carry the local text until the server holds the current text.
 * A failed or pending upload keeps the local copy, so an edit is never lost.
 */
export function cloudTaskCarriesLocalInstructions(input: {
  flagEnabled: boolean;
  projectId: number | null;
  onServer: Readonly<Record<string, string>>;
  local: string | null;
}): boolean {
  return !(
    input.flagEnabled &&
    input.projectId != null &&
    input.local != null &&
    input.onServer[String(input.projectId)] === input.local
  );
}
