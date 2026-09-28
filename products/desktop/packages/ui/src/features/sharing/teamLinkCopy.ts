import type { ShareVisibility } from "./shareTarget";

const COPY: Record<ShareVisibility, Record<"canvas" | "file", string>> = {
  project: {
    canvas: "Everyone on your team can open it straight in PostHog Desktop.",
    file: "Everyone on your team with access to the task can open it straight in PostHog Desktop.",
  },
  private: {
    canvas:
      "Only members of this space can open it. Add someone to the space to let them in.",
    file: "Only members of this space with access to the task can open it. Add someone to the space to let them in.",
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
 *  statement rather than a control until per-item permissions exist.
 *  A canvas can also be closed to individual teammates by an object-level rule,
 *  which the space alone cannot express, so the project wording stays about the space. */
export function teamLinkDescription(
  visibility: ShareVisibility,
  noun: "canvas" | "file",
): string {
  return COPY[visibility][noun];
}
