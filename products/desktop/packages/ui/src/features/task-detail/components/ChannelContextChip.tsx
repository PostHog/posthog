import { channelDisplayLabel } from "@posthog/core/canvas/channelName";
import {
  Chip,
  ChipClose,
  cn,
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@posthog/quill";

type ChannelContextChipProps = {
  channelName?: string;
  onView?: () => void;
} & (
  | { source: "context-layer"; onRemove?: never }
  | { source: "legacy"; onRemove: () => void }
);

export function ChannelContextChip(props: ChannelContextChipProps) {
  const { channelName, onView, source } = props;
  const label = source === "context-layer" ? "Context layer" : "CONTEXT.md";
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
      {label}
      {source === "legacy" ? (
        <ChipClose
          aria-label={`Remove ${channelName ? `${channelDisplayLabel(channelName)} ` : ""}CONTEXT.md`}
          className="mr-[-2.5px]"
          onClick={(event) => {
            event.stopPropagation();
            props.onRemove();
          }}
        />
      ) : null}
    </Chip>
  );

  if (!onView && source === "legacy") return chip;

  return (
    <Tooltip>
      <TooltipTrigger render={chip} />
      <TooltipContent side="top">
        {source === "context-layer"
          ? "Context layer is always connected"
          : "Click to view CONTEXT.md"}
      </TooltipContent>
    </Tooltip>
  );
}
