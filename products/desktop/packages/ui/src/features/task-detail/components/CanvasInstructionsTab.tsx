import { Box, ScrollArea, Text } from "@radix-ui/themes";
import { MarkdownRenderer } from "../../editor/components/MarkdownRenderer";

interface CanvasInstructionsTabProps {
  body: string;
}

// Renders the canvas generation instructions exactly as they were sent with the
// task's prompt. Read-only snapshot — the body is carried in the tab data, not
// re-derived, so it reflects the authoring contract the agent actually received.
export function CanvasInstructionsTab({ body }: CanvasInstructionsTabProps) {
  return (
    <ScrollArea type="auto" scrollbars="vertical" className="h-full">
      <Box p="4">
        <Text className="mb-3 block text-[12px] text-gray-9">
          Sent with this task's prompt — the canvas authoring contract the agent
          followed.
        </Text>
        <Box className="text-[13px]">
          <MarkdownRenderer content={body} />
        </Box>
      </Box>
    </ScrollArea>
  );
}
