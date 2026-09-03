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
// Drawn at the row-icon size the rest of the app spins at, not at the dot's own
// 8px: eight dots inside an 8px box are 1.6px across, and that reads as a smudge
// rather than as something turning, which leaves the one row that is working the
// faintest mark in the list.
const SPINNER_SIZE = 12;
// The box the ring is centered in and measured by. It stays the plain dot's, so
// the icon column holds one width and a working row's label lines up with its
// neighbours' — the ring's extra width spills evenly into the row's padding.
const SPINNER_BOX = DOT_SIZE;
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
export function RowTooltip({
  label,
  side,
  children,
}: {
  label: string;
  /** Where the row sits: `bottom` for the window header, which has no room above. */
  side: "top" | "right" | "bottom";
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
 * The dot itself, as a plain element. A function rather than a component so the
 * result is a DOM element a tooltip trigger can clone — and so the mark can be
 * drawn on its own where the state is already named in words beside it.
 *
 * `decorative` is for that second case: where the label is on screen already,
 * naming the dot as well says it twice.
 */
function dotMark(dot: TaskDot, decorative = false): ReactElement {
  const color = DOT_TONE_VAR[dot.tone];
  const naming = decorative
    ? { "aria-hidden": true }
    : { "aria-label": dot.label, role: "img" };
  if (dot.spinner) {
    return (
      <span
        {...naming}
        className="relative flex shrink-0 items-center justify-center"
        // The spinner draws its dots in `currentColor`, so the tone is set
        // here rather than passed down.
        style={{
          color: TONE_ICON_VAR[dot.tone],
          width: SPINNER_BOX,
          height: SPINNER_BOX,
        }}
      >
        <DotRingSpinner
          size={SPINNER_SIZE}
          // Out of flow, so the box measures the dot rather than the ring.
          className="-translate-x-1/2 -translate-y-1/2 absolute top-1/2 left-1/2"
        />
      </span>
    );
  }
  return (
    <span
      {...naming}
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
  );
}

/**
 * A task's state as a single dot: blue wants a decision, the brand yellow is
 * working or unread, grey is quiet. The trigger renders as a span because rows are
 * `<button>`s — a nested button would be invalid HTML.
 */
export function TaskStatusDot({ dot }: { dot: TaskDot }) {
  return (
    <RowTooltip label={dot.label} side="right">
      {dotMark(dot)}
    </RowTooltip>
  );
}

/**
 * The same dot without the tooltip, for surfaces that already say what it means
 * — the hover card names the state in words right beside it, and a tooltip over
 * a label is a second answer to a question nobody asked twice.
 */
export function TaskDotMark({ dot }: { dot: TaskDot }) {
  return dotMark(dot, true);
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
 * A task's identity as stacked avatars: the pin, then source and PR/branch. The
 * pin goes first, which in a reversed stack puts it leftmost and underneath — it
 * says how the row got here, not what came out of it.
 *
 * A row with nothing to say gets no stack at all, rather than an empty group
 * whose padding would still push the row's other content around.
 */
export function TaskBadgeStack({
  status,
  pinned,
}: {
  status: TaskStatusInput;
  pinned?: boolean;
}) {
  const badges = taskBadges(status);
  if (!pinned && badges.length === 0) {
    return null;
  }
  return (
    <AvatarGroup stacked reverse size="xs" className="shrink-0">
      {pinned ? <PinnedBadge /> : null}
      {badges.map(({ key, Icon, label, tone }) => (
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
