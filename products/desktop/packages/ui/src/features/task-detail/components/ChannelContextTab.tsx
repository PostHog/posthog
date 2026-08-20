import { channelDisplayReference } from "@posthog/core/canvas/channelName";
import { Box, ScrollArea } from "@radix-ui/themes";
import { MarkdownRenderer } from "../../editor/components/MarkdownRenderer";

interface ChannelContextTabProps {
  channelName: string | null;
  body: string;
}

// Renders a channel's CONTEXT.md exactly as it was sent with the task's prompt.
// Read-only snapshot — the body is carried in the tab data, not re-fetched, so
// it reflects what the agent received even if the live CONTEXT.md later changes.
export function ChannelContextTab({
  channelName,
  body,
}: ChannelContextTabProps) {
  return (
    <ScrollArea type="auto" scrollbars="vertical" className="h-full">
      <Box p="4">
        <p className="mb-3 text-[12px] text-gray-9">
          Sent with this task's prompt as background context
          {channelName ? ` from ${channelDisplayReference(channelName)}` : ""}.
        </p>
        <Box className="text-[13px]">
          <MarkdownRenderer content={body} />
        </Box>
      </Box>
    </ScrollArea>
  );
}
