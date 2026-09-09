import { SKETCHPAD_FIELD_MAX_REMOVED } from "@posthog/shared";

export const COPY_SKETCHPAD_LINK_ACTION = "Copy link";

export const NEW_SKETCHPAD_TEMPLATE_NAME = "Sketchpad";
export const NEW_SKETCHPAD_TEMPLATE_HINT =
  "Live fragments on an infinite board.";

export const DEFAULT_SKETCHPAD_NAME = "Untitled sketchpad";
export const DIALOG_CANCEL = "Cancel";

export const TOOLBAR_HISTORY = "History";
export const TOOLBAR_STATE = "State";

export const SKETCHPAD_FRAME_TITLE = "Sketchpad fragments";

export function duplicateFragmentsAction(count: number): string {
  return `Duplicate ${fragmentCountLabel(count)}`;
}

export function bringFragmentsToFrontAction(count: number): string {
  return `Bring ${fragmentCountLabel(count)} to front`;
}

export function deleteFragmentsAction(count: number): string {
  return `Delete ${fragmentCountLabel(count)}`;
}

export const EDIT_FRAGMENT_SUBMIT = "Save fragment";

export function fragmentCodeBlockedReason(
  violations: readonly string[],
): string {
  return `${violations.join("; ")}.`;
}

export function lastEditedByLabel(name: string, when: string): string {
  return `Last edited by ${name}, ${when}`;
}

export function collaboratorsLabel(count: number): string {
  return count === 1 ? "1 other editing" : `${count} others editing`;
}

export function presenceOverflowLabel(count: number): string {
  return `+${count}`;
}

export function STATE_USED_BY(readers: readonly string[]): string {
  if (readers.length <= 3) return `Read by ${readers.join(", ")}`;
  return `Read by ${readers.slice(0, 3).join(", ")}, and ${readers.length - 3} more`;
}

export const CHAT_EXAMPLES: readonly string[] = [
  "Add a card that counts signups this week",
  "Chart active people per day for the last 30 days",
  "Show the top five pages by views",
];

export function fragmentCountLabel(count: number): string {
  return count === 1 ? "1 fragment" : `${count} fragments`;
}

export const SHARED_TEXT_CHANGES_FULL = `This text has ${SKETCHPAD_FIELD_MAX_REMOVED.toLocaleString("en-US")} deleted characters in it, which is the limit. Copy the text into a new fragment to go on.`;

export const SKETCHPAD_TOO_MANY_READS_AT_ONCE =
  "This fragment asked for too much data at once. Wait for the data it already asked for.";

export function sketchpadReadsPausedMessage(seconds: number): string {
  return `This board is reading data too fast. Try again in ${secondsPhrase(seconds)}.`;
}

export function sketchpadWritesPausedMessage(seconds: number): string {
  return `This board is changing shared state too fast. Try again in ${secondsPhrase(seconds)}.`;
}

function secondsPhrase(seconds: number): string {
  const whole = Math.max(1, Math.ceil(seconds));
  return whole === 1 ? "1 second" : `${whole} seconds`;
}

export const CHAT_START_ERROR = "Could not start the session";

export const SKETCHPAD_REQUEST_TOO_LARGE =
  "This fragment sent too much data in one call. Send it in smaller pieces.";
