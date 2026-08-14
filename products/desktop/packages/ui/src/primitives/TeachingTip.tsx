import { Popover as BaseUIPopover } from "@base-ui/react/popover";
import {
  Button,
  cn,
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@posthog/quill";
import { electronStorage } from "@posthog/ui/shell/rendererStorage";
import type { ReactNode } from "react";
import { useState } from "react";
import { create } from "zustand";
import { persist } from "zustand/middleware";

interface TeachingTipStore {
  /** Tips this person has retired, by id. Persisted: "don't show again" has to
   *  outlive the window it was clicked in. */
  retired: Record<string, boolean | undefined>;
  /** Whether the persisted answer has arrived. Nothing is taught before it, or
   *  every restart would flash the tips someone already retired. */
  hydrated: boolean;
  retire: (id: string) => void;
  reset: () => void;
}

const useTeachingTipStore = create<TeachingTipStore>()(
  persist(
    (set) => ({
      retired: {},
      hydrated: false,
      retire: (id) =>
        set((state) => ({ retired: { ...state.retired, [id]: true } })),
      reset: () => set({ retired: {} }),
    }),
    {
      name: "teaching-tips",
      storage: electronStorage,
      partialize: (state) => ({ retired: state.retired }),
      // Also on a failed read: a store that can't answer should stop holding
      // its tips back rather than silence them forever.
      onRehydrateStorage: () => () =>
        useTeachingTipStore.setState({ hydrated: true }),
    },
  ),
);

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
 * Retire a tip from outside it: the thing a tip points at counts as the lesson
 * learned, so acting on it should also be the last time the tip is offered.
 */
export function retireTeachingTip(id: string): void {
  useTeachingTipStore.getState().retire(id);
}

/**
 * Offer every retired tip again. "Don't show again" is otherwise a one-way
 * door, and the tips point at parts of the app a person may well come back to.
 */
export function resetTeachingTips(): void {
  useTeachingTipStore.getState().reset();
}

/** How many tips this person has turned off, for a surface that offers them back. */
export function useRetiredTipCount(): number {
  return useTeachingTipStore(
    (state) => Object.values(state.retired).filter(Boolean).length,
  );
}

/**
 * A one-off callout anchored to the thing it is teaching: "this is where that
 * went". The caller says when the moment is right; the tip decides whether it
 * has already been taught.
 *
 * Built on a popover rather than quill's `anchoredToast`, which anchors fine
 * but drops what this needs: its viewport renders a card with only a title and
 * a description, passing neither the `action` nor the `onDismiss` that
 * `ToastCard` accepts and the stacked viewport passes. So an anchored toast
 * has no buttons to put "Don't show again" and "Dismiss" on.
 */
export function TeachingTip({
  id,
  open,
  message,
  side = "bottom",
  align = "end",
  className,
  children,
}: {
  /** Stable key for this lesson. Retiring it is permanent and per person. */
  id: string;
  /** Whether the caller's moment has arrived; the tip may still stay closed. */
  open: boolean;
  message: ReactNode;
  side?: "top" | "bottom" | "left" | "right";
  align?: "start" | "center" | "end";
  className?: string;
  /** What the tip points at. */
  children: ReactNode;
}) {
  const retired = useTeachingTipStore((state) => state.retired[id]);
  const hydrated = useTeachingTipStore((state) => state.hydrated);
  const retire = useTeachingTipStore((state) => state.retire);
  // Put away for this moment. Dismissing is the caller's next moment, not the
  // end of them: any close (the Dismiss button, a click outside, Escape) sets
  // this, and it lifts when the caller opens a new one.
  const [hidden, setHidden] = useState(false);
  const [offered, setOffered] = useState(open);
  if (open !== offered) {
    setOffered(open);
    if (open) setHidden(false);
  }
  const showing = open && hydrated && !retired && !hidden;

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
        {/* Left aligned, so the primary action starts on the same edge as the
            sentence above it. */}
        <div className="flex justify-start gap-1">
          {/* "Got it" is the lesson landing, so it retires the tip; "Dismiss"
              only clears this one. Settings puts back anything retired here. */}
          <Button size="sm" variant="primary" onClick={() => retire(id)}>
            Got it
          </Button>
          <Button size="sm" onClick={() => setHidden(true)}>
            Dismiss
          </Button>
        </div>
      </PopoverContent>
    </Popover>
  );
}
