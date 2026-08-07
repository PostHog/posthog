import { PushPin } from "@phosphor-icons/react";
import {
  Avatar,
  AvatarFallback,
  AvatarGroup,
  cn,
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@posthog/quill";
import {
  DOT_TONE_VAR,
  type TaskDot,
  type TaskStatusInput,
  TONE_ICON_VAR,
  taskBadges,
} from "@posthog/ui/features/sidebar/components/items/taskStatusVocabulary";
import { DotRingSpinner } from "@posthog/ui/primitives/DotRingSpinner";
import type { ReactElement, ReactNode } from "react";

const DOT_SIZE = 8;
// Exactly the plain dot's box. Anything larger and a working row's label starts
// further right than its neighbours' — the icon column has to hold one width or
// the list stops looking like a list.
const SPINNER_SIZE = DOT_SIZE;
// Enough to still find the dot if you look for it, not enough to count as one of
// the list's live rows.
const FAINT_OPACITY = 0.4;
// One provider per row, so a row's dot and badges share a hover delay and handing
// off between them doesn't re-wait.
const TOOLTIP_DELAY_MS = 200;

/**
 * A label-only tooltip. Two things keep it out of the way, because one isn't
 * enough: `disableHoverablePopup` stops Base UI holding the popup open when the
 * pointer moves onto it, and `pointer-events-none` is the guarantee — a popup
 * that can't receive the pointer can't be hovered, can't swallow a click meant
 * for the row underneath, and can't have its text dragged into a selection.
 */
function RowTooltip({
  label,
  side,
  children,
}: {
  label: string;
  side: "top" | "right";
  children: ReactElement;
}) {
  return (
    <Tooltip disableHoverablePopup>
      <TooltipTrigger render={children} />
      <TooltipContent side={side} className="pointer-events-none select-none">
        {label}
      </TooltipContent>
    </Tooltip>
  );
}

/**
 * A task's state as a single dot: blue wants a decision, the brand yellow is
 * working or unread, grey is quiet. The trigger renders as a span because rows are
 * `<button>`s — a nested button would be invalid HTML.
 */
export function TaskStatusDot({ dot }: { dot: TaskDot }) {
  const color = DOT_TONE_VAR[dot.tone];
  if (dot.spinner) {
    return (
      <RowTooltip label={dot.label} side="right">
        <span
          aria-label={dot.label}
          role="img"
          className="flex shrink-0 items-center justify-center"
          // The spinner draws its dots in `currentColor`, so the tone is set
          // here rather than passed down.
          style={{ color: TONE_ICON_VAR[dot.tone], width: SPINNER_SIZE }}
        >
          <DotRingSpinner size={SPINNER_SIZE} />
        </span>
      </RowTooltip>
    );
  }
  return (
    <RowTooltip label={dot.label} side="right">
      <span
        aria-label={dot.label}
        role="img"
        className={cn(
          "block shrink-0 rounded-full",
          // ph-pulse is the app's existing flash, but it has no reduced-motion
          // rule of its own — hold a static dot rather than blinking at someone
          // who asked us not to.
          dot.pulse && "ph-pulse motion-reduce:animate-none",
        )}
        style={{
          width: DOT_SIZE,
          height: DOT_SIZE,
          backgroundColor: dot.style === "solid" ? color : "transparent",
          boxShadow:
            dot.style === "hollow" ? `inset 0 0 0 1.5px ${color}` : undefined,
          opacity: dot.faint ? FAINT_OPACITY : undefined,
        }}
      />
    </RowTooltip>
  );
}

/**
 * The pin: this row was put here on purpose. Lives with the badges because it
 * belongs in their stack — pinned rows sit in the one list with everything else,
 * so the badge is what says a row is pinned.
 *
 * Amber rather than the vocabulary's `--primary` yellow: primary means "there is
 * something here for you", and a pin is a shelf, not a claim on your attention.
 */
export function PinnedBadge() {
  return (
    <RowTooltip label="Pinned" side="top">
      <Avatar
        size="xs"
        aria-label="Pinned"
        role="img"
        className="cursor-default"
      >
        <AvatarFallback className="bg-transparent">
          <PushPin size={9} className="text-primary" />
        </AvatarFallback>
      </Avatar>
    </RowTooltip>
  );
}

/**
 * A task's identity as stacked avatars: the pin, then source, cloud, and
 * PR/branch. The pin goes first, which in a reversed stack puts it leftmost and
 * underneath — it says how the row got here, not what came out of it.
 */
export function TaskBadgeStack({
  status,
  pinned,
}: {
  status: TaskStatusInput;
  pinned?: boolean;
}) {
  return (
    <AvatarGroup stacked reverse size="xs" className="shrink-0">
      {pinned ? <PinnedBadge /> : null}
      {taskBadges(status).map(({ key, Icon, label, tone }) => (
        <RowTooltip key={key} label={label} side="top">
          {/* The tooltip names the badge on hover; `aria-label` is what names it
              for everyone else — without it the stack is a row of blank avatars
              to a screen reader. */}
          {/* `cursor-default`: these name a fact about the row, they aren't
              controls — quill gives an avatar rendered as a button the pointer
              cursor, which promises a click that does nothing. */}
          <Avatar
            size="xs"
            aria-label={label}
            role="img"
            className="cursor-default"
          >
            <AvatarFallback className="bg-transparent text-muted-foreground">
              {/* An explicit `color` (an SVG fill) rather than a text-* class,
                  so a hovered or selected row can't reset it — the same reason
                  TaskIcon does this. */}
              <Icon
                size={9}
                weight={tone ? "fill" : "regular"}
                color={tone ? TONE_ICON_VAR[tone] : undefined}
                className={tone ? undefined : "text-muted-foreground/50"}
              />
            </AvatarFallback>
          </Avatar>
        </RowTooltip>
      ))}
    </AvatarGroup>
  );
}

/**
 * Wraps a row's dot and badges in one tooltip provider, so hovering from the dot
 * to a badge doesn't re-wait the open delay.
 */
export function TaskStatusTooltips({ children }: { children: ReactNode }) {
  return <TooltipProvider delay={TOOLTIP_DELAY_MS}>{children}</TooltipProvider>;
}
