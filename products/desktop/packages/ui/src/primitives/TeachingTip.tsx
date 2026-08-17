import { Popover as BaseUIPopover } from "@base-ui/react/popover";
import {
  Button,
  cn,
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@posthog/quill";
import { useSettingsStore } from "@posthog/ui/features/settings/settingsStore";
import type { ReactNode } from "react";
import { useState } from "react";

/**
 * The triangle itself: filled in the tip's own border color, with the border
 * drawn as two strokes so the arrow reads as a piece of the card's outline
 * rather than a shape sitting on top of it.
 */
function ArrowGlyph() {
  return (
    <svg width="14" height="8" viewBox="0 0 14 8" aria-hidden>
      <title>Arrow</title>
      {/* `--card` is what quill fills the popup with, so the arrow's body is
          the same surface continuing past the card's edge. */}
      <path d="M0 0 L7 7 L14 0" fill="var(--card)" />
      <path
        d="M0 0 L7 7 L14 0"
        fill="none"
        stroke="currentColor"
        strokeWidth="1"
      />
    </svg>
  );
}

/**
 * A one-off callout anchored to the thing it is teaching: "this is where that
 * went". The caller says when the moment is right; the tip decides whether it
 * has already been taught.
 *
 * Built on a popover rather than quill's `anchoredToast`. The anchored toast
 * carries an action and a close button as of quill 0.3.0-beta.28, so the
 * buttons are no longer the blocker, but its card has no arrow and centers on
 * its anchor: it lands beside the control rather than pointing at it, which is
 * the whole job of a tip that says "this is where that went".
 *
 * Backed by the same keyed `hints` the toast hints use, so both answer to the
 * one switch in settings. Unlike a hint it never records a showing: a tip is
 * offered every occasion until it is answered, because it is pointing at
 * something a reader can act on rather than reporting something that already
 * happened.
 */
export function TeachingTip({
  id,
  open,
  moment,
  message,
  side = "bottom",
  align = "end",
  className,
  children,
}: {
  /** Stable key for this lesson, from `TIP_KEYS`. Answering it is permanent
   *  and per person. */
  id: string;
  /** Whether the caller's moment has arrived; the tip may still stay closed. */
  open: boolean;
  /**
   * Which occasion this is, when `open` stays true across several of them. A
   * new value is a new occasion, so a tip put away for the last one comes back
   * for this one. Without it, a caller whose `open` never dips has one chance
   * to teach the lesson and loses it to a stray click outside.
   */
  moment?: string | number;
  message: ReactNode;
  side?: "top" | "bottom" | "left" | "right";
  align?: "start" | "center" | "end";
  className?: string;
  /** What the tip points at. */
  children: ReactNode;
}) {
  const learned = useSettingsStore((state) => state.hints[id]?.learned);
  const enabled = useSettingsStore((state) => state.tipsEnabled);
  // Nothing is taught before the persisted answers arrive, or every restart
  // would flash the tips someone has already hidden.
  const hydrated = useSettingsStore((state) => state._hasHydrated);
  const markLearned = useSettingsStore((state) => state.markHintLearned);
  // Put away for this occasion only. Closing the tip without answering it (a
  // click outside, Escape) sets this, and the next occasion lifts it: only
  // "Hide" ends the lesson.
  const [hidden, setHidden] = useState(false);
  const [offered, setOffered] = useState({ open, moment });
  if (offered.open !== open || offered.moment !== moment) {
    setOffered({ open, moment });
    if (open) setHidden(false);
  }
  const showing = open && enabled && hydrated && !learned && !hidden;

  return (
    <Popover
      open={showing}
      onOpenChange={(next) => {
        if (!next) setHidden(true);
      }}
    >
      {/* A wrapper rather than the control itself: the control is often already
          a trigger for something else (a tooltip, a menu), and one element
          cannot be two triggers. `tabIndex={-1}` takes back the stop Base UI
          gives a trigger, which would otherwise sit in the tab order in front
          of the real control inside it. */}
      <PopoverTrigger
        tabIndex={-1}
        nativeButton={false}
        render={<span className={cn("inline-flex", className)} />}
      >
        {children}
      </PopoverTrigger>
      {/* Nobody asked for this popup, so it does not take the caret: it opens
          on its own when a turn ends, and the reader may well be typing. */}
      <PopoverContent
        side={side}
        align={align}
        initialFocus={false}
        className="w-56 gap-2 border-primary"
      >
        {/* Base UI's own arrow rather than a corner-pinned triangle: it reads
            the positioner, so it keeps pointing at the control after a flip or
            a shift off the viewport edge. quill has no arrow of its own, and
            Base UI is the layer quill's popover is already built on. */}
        {/* 6px, not the glyph's full 7: the last pixel sits back over the
            card's border, so the arrow's fill covers the segment of outline
            that would otherwise run across its mouth. */}
        <BaseUIPopover.Arrow className="data-[side=bottom]:-top-[6px] data-[side=left]:-right-[6px] data-[side=right]:-left-[6px] data-[side=top]:-bottom-[6px] data-[side=right]:-rotate-90 text-primary data-[side=bottom]:rotate-180 data-[side=left]:rotate-90">
          <ArrowGlyph />
        </BaseUIPopover.Arrow>
        <p className="text-[13px]">{message}</p>
        {/* Left aligned, so the action starts on the same edge as the sentence
            above it. */}
        <div className="flex justify-start gap-1">
          {/* The one way to end the lesson, so it is the only button: closing
              the tip any other way is putting it away for now. Settings puts
              back anything hidden here. */}
          <Button size="sm" variant="primary" onClick={() => markLearned(id)}>
            Hide
          </Button>
        </div>
      </PopoverContent>
    </Popover>
  );
}
