import { Attachment } from "@posthog/ui/features/message-editor/components/Attachment";

/**
 * The channel CONTEXT.md riding along with the prompt, shown in the composer's
 * attachments row. Deliberately the same component the user's own attachments
 * use, because that is what it is from the writer's point of view: something
 * extra travelling with the message, which they can inspect or drop.
 */
export function ChannelContextChip({
  channelName,
  onView,
  onRemove,
}: {
  channelName?: string;
  onView?: () => void;
  onRemove: () => void;
}) {
  return (
    <Attachment
      label={`${channelName ? `#${channelName} ` : ""}CONTEXT.md`}
      hint={onView ? "Click to view" : undefined}
      onOpen={onView}
      onRemove={onRemove}
    />
  );
}
