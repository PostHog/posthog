import { Label, Text } from "@posthog/quill";
import type { ShareVisibility } from "./shareTarget";

const COPY: Record<ShareVisibility, Record<"canvas" | "file", string>> = {
  project: {
    canvas: "Everyone on your team. The canvas is in a shared space.",
    file: "Everyone on your team. The task is in a shared space.",
  },
  personal: {
    canvas:
      "Only you. The canvas is in your personal space. Move it to a shared space to let teammates open it.",
    file: "Only you. The task is in your personal space. Move it to a shared space to let teammates open it.",
  },
  unknown: {
    canvas: "Checking who can open this canvas…",
    file: "Checking who can open this file…",
  },
};

/** Who the internal link works for. Access follows the space, so this is a
 *  statement rather than a control until per-item permissions exist. */
export function AccessSection({
  visibility,
  noun,
}: {
  visibility: ShareVisibility;
  noun: "canvas" | "file";
}) {
  return (
    <div className="flex flex-col gap-1.5">
      <Label>Who can open the team link</Label>
      <Text size="xs" variant="muted">
        {COPY[visibility][noun]}
      </Text>
    </div>
  );
}
