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
 * The space context riding along with the prompt, pinned inside the composer
 * beside the send button rather than sitting in the attachments row. It isn't
 * an attachment the writer chose: it comes with the space and travels with
 * every prompt sent from it, so it keeps its own spot and shows its name
 * instead of collapsing to an extension square like a real attachment does.
 *
 * Without `onRemove` the chip is read-only: it names a context-wiki page, which
 * the agent keeps mounted for the whole session and cannot drop per task.
 */
export function ChannelContextChip({
  label,
  channelName,
  onView,
  onRemove,
}: {
  label: string;
  channelName?: string;
  onView?: () => void;
  onRemove?: () => void;
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
        "mt-px shrink-0 text-[11px]",
        onRemove && "pr-1",
        !onView && "cursor-default",
      )}
    >
      {label}
      {/* Always rendered, not revealed on hover: the chip sets the editor's
          right padding, so a width that changes under the cursor would reflow
          the text being typed. */}
      {onRemove ? (
        <ChipClose
          aria-label={`Remove ${channelName ? `${channelDisplayLabel(channelName)} ` : ""}${label}`}
          className="mr-[-2.5px]"
          onClick={(event) => {
            // The chip itself opens the file; removing it must not also do that.
            event.stopPropagation();
            onRemove();
          }}
        />
      ) : null}
    </Chip>
  );

  const hint = onRemove
    ? onView && `Click to view ${label}`
    : `${label} goes to every task in this space.${onView ? " Click to view." : ""}`;

  if (!hint) return chip;

  return (
    <Tooltip>
      <TooltipTrigger render={chip} />
      <TooltipContent side="top">{hint}</TooltipContent>
    </Tooltip>
  );
}
