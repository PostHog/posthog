import { getErrorMessage, SKILL_EXISTS_MARKER } from "@posthog/shared";

/** Write endpoints throw plain Errors; conflicts match the shared marker. */
export function isSkillExistsError(error: unknown): boolean {
  return getErrorMessage(error).includes(SKILL_EXISTS_MARKER);
}

/** Toast-friendly error description: the message, or nothing. */
export function skillErrorDescription(error: unknown): string | undefined {
  return getErrorMessage(error) || undefined;
}
