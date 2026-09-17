import type { ShareVisibility } from "./shareTarget";

const COPY: Record<ShareVisibility, Record<"canvas" | "file", string>> = {
  project: {
    canvas: "Everyone on your team can open it straight in PostHog Desktop.",
    file: "Everyone on your team with access to the task can open it straight in PostHog Desktop.",
  },
  personal: {
    canvas:
      "Only you can open it. Move the canvas to a shared space to let your team in.",
    file: "Only you can open it. Move the task to a shared space to let your team in.",
  },
  unknown: {
    canvas: "Opens the canvas straight in PostHog Desktop.",
    file: "Opens the file straight in PostHog Desktop.",
  },
};

/** Who the team link works for. Access follows the space, so this is a
 *  statement rather than a control until per-item permissions exist. */
export function teamLinkDescription(
  visibility: ShareVisibility,
  noun: "canvas" | "file",
): string {
  return COPY[visibility][noun];
}
