import { channelDisplayLabel } from "@posthog/core/canvas/channelName";
import {
  Chip,
  ChipClose,
  cn,
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@posthog/quill";

/**
 * The channel CONTEXT.md riding along with the prompt, pinned inside the
 * composer beside the send button rather than sitting in the attachments row.
 * It isn't an attachment the writer chose: it comes with the space and travels
 * with every prompt sent from it, so it keeps its own spot and shows its name
 * instead of collapsing to an extension square like a real attachment does.
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
  const chip = (
    <Chip
      onClick={onView}
      size="sm"
      // Chip renders a <div> so ChipClose can nest legally, but the button
      // behaviour underneath assumes a real <button> unless told otherwise.
      // Without this it never binds Enter/Space, so the chip is reachable by
      // keyboard and then does nothing.
      nativeButton={false}
      className={cn(
        "mt-px shrink-0 pr-1 text-[11px]",
        !onView && "cursor-default",
      )}
    >
      CONTEXT.md
      {/* Always rendered, not revealed on hover: the chip sets the editor's
          right padding, so a width that changes under the cursor would reflow
          the text being typed. */}
      <ChipClose
        aria-label={`Remove ${channelName ? `${channelDisplayLabel(channelName)} ` : ""}CONTEXT.md`}
        className="mr-[-2.5px]"
        onClick={(event) => {
          // The chip itself opens the file; removing it must not also do that.
          event.stopPropagation();
          onRemove();
        }}
      />
    </Chip>
  );

  if (!onView) return chip;

  return (
    <Tooltip>
      <TooltipTrigger render={chip} />
      <TooltipContent side="top">Click to view CONTEXT.md</TooltipContent>
    </Tooltip>
  );
}
