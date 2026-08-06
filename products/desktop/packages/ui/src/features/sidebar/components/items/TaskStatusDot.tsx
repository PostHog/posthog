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
import type { ReactElement, ReactNode } from "react";

// One width for every state, working included: a dot that grew while it ran
// would start its row's label further right than its neighbours', and the icon
// column has to hold one width or the list stops looking like a list.
const DOT_SIZE = 8;
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
 * working or unread, grey is quiet. The trigger renders as a span because rows
 * are `<button>`s — a nested button would be invalid HTML.
 *
 * The pin is not here. A mark on the dot has to compete with the state the dot
 * is already reporting, and the two say unrelated things — a section of its own
 * carries it instead.
 */
export function TaskStatusDot({ dot }: { dot: TaskDot }) {
  const color = DOT_TONE_VAR[dot.tone];
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
 * A task's identity as stacked avatars: source, local, and PR/branch — what came
 * out of the row, in the order it was acquired. The pin isn't here: it says
 * something about where the row sits rather than what it produced, and it rings
 * the dot instead.
 *
 * Often empty. A cloud task that opened no PR has nothing to say here, and the
 * stack simply takes no room.
 */
export function TaskBadgeStack({ status }: { status: TaskStatusInput }) {
  return (
    <AvatarGroup stacked reverse size="xs" className="shrink-0">
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
