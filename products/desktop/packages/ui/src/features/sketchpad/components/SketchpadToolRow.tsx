import { sketchpadToolName } from "@posthog/core/sketchpad/toolCalls";
import { Badge, Text } from "@posthog/quill";
import type { ToolViewProps } from "@posthog/ui/features/sessions/components/session-update/toolCallUtils";

const LABELS: Record<string, string> = {
  sketchpad_add_fragment: "Added a fragment",
  sketchpad_update_fragment: "Changed a fragment",
  sketchpad_remove_fragment: "Removed a fragment",
  sketchpad_set_state: "Set shared state",
  sketchpad_list_fragments: "Read the board",
  sketchpad_get_fragment: "Read a fragment",
  sketchpad_get_state: "Read shared state",
};

export function SketchpadToolRow({ toolCall }: ToolViewProps) {
  const tool = sketchpadToolName(toolCall._meta);
  if (!tool) return null;
  const target = readTarget(toolCall.rawInput);

  return (
    <div className="flex items-center gap-2">
      <Badge variant="default">Sketchpad</Badge>
      <Text size="xs" variant="muted">
        {LABELS[tool] ?? tool}
        {target ? `: ${target}` : ""}
      </Text>
    </div>
  );
}

function readTarget(rawInput: unknown): string | null {
  if (typeof rawInput !== "object" || rawInput === null) return null;
  const record = rawInput as Record<string, unknown>;
  const value = record.id ?? record.key;
  return typeof value === "string" ? value : null;
}
