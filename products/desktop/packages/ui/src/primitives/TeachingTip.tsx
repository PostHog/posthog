import { Popover as BaseUIPopover } from "@base-ui/react/popover";
import {
  Button,
  cn,
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@posthog/quill";
import {
  type HintState,
  isHintRetired,
  useSettingsStore,
} from "@posthog/ui/features/settings/settingsStore";
import { useRendererWindowFocusStore } from "@posthog/ui/shell/rendererWindowFocusStore";
import type { ReactNode } from "react";
import { useEffect, useRef, useState } from "react";

function discountOwnShowing(
  hint: HintState | undefined,
  recorded: boolean,
): HintState | undefined {
  if (!recorded || !hint || hint.learned) return hint;
  return { ...hint, count: Math.max(0, hint.count - 1) };
}

function ArrowGlyph() {
  return (
    <svg width="14" height="8" viewBox="0 0 14 8" aria-hidden>
      <title>Arrow</title>
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
 * A one-off callout anchored to the control it teaches. The caller decides when
 * the moment is right; the tip decides whether it has already been answered.
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
  /** Stable key for this lesson, from `TIP_KEYS`. Answered permanently, per person. */
  id: string;
  open: boolean;
  /**
   * Distinguishes occasions when `open` stays true across several of them, so a
   * tip put away for one comes back for the next.
   */
  moment?: string | number;
  message: ReactNode;
  side?: "top" | "bottom" | "left" | "right";
  align?: "start" | "center" | "end";
  className?: string;
  children: ReactNode;
}) {
  const hint = useSettingsStore((state) => state.hints[id]);
  const tipsEnabled = useSettingsStore((state) => state.tipsEnabled);
  // Wait for persisted answers, or a restart would flash already-hidden tips.
  const hydrated = useSettingsStore((state) => state._hasHydrated);
  const markLearned = useSettingsStore((state) => state.markHintLearned);
  // Dismissing without answering (click outside, Escape) hides for this occasion
  // only; the next occasion lifts it. Only "Hide" ends the lesson.
  const [hidden, setHidden] = useState(false);
  const [offered, setOffered] = useState({ open, moment });
  if (offered.open !== open || offered.moment !== moment) {
    setOffered({ open, moment });
    if (open) setHidden(false);
  }
  const inFront = useRendererWindowFocusStore((state) => state.focused);
  const episode = useRef({ recorded: false });
  const offerable =
    tipsEnabled &&
    !isHintRetired(id, discountOwnShowing(hint, episode.current.recorded));
  const showing = open && offerable && hydrated && !hidden;
  useEffect(() => {
    if (!showing) {
      episode.current.recorded = false;
      return;
    }
    // A turn ending puts the tip back up whether or not anybody is watching,
    // and turns run long enough that the window is often behind another app by
    // then. Nothing is taught there, so spend the showing once the window comes
    // back in front. Focus leaving and returning is still the same showing.
    if (!inFront || episode.current.recorded) return;
    episode.current.recorded = true;
    useSettingsStore.getState().recordHintShown(id);
  }, [showing, inFront, id]);

  return (
    <Popover
      open={showing}
      onOpenChange={(next) => {
        if (!next) setHidden(true);
      }}
    >
      {/* Wrap the control instead of making it the trigger: it may already be a
          trigger for something else. tabIndex={-1} keeps the wrapper out of the
          tab order in front of the real control. */}
      <PopoverTrigger
        tabIndex={-1}
        nativeButton={false}
        render={<span className={cn("inline-flex", className)} />}
      >
        {children}
      </PopoverTrigger>
      {/* Opens on its own when a turn ends, so it must not steal focus from a
          reader who may be typing. */}
      <PopoverContent
        side={side}
        align={align}
        initialFocus={false}
        className="w-56 gap-2 border-primary"
      >
        <BaseUIPopover.Arrow className="data-[side=bottom]:-top-[6px] data-[side=left]:-right-[6px] data-[side=right]:-left-[6px] data-[side=top]:-bottom-[6px] data-[side=right]:-rotate-90 text-primary data-[side=bottom]:rotate-180 data-[side=left]:rotate-90">
          <ArrowGlyph />
        </BaseUIPopover.Arrow>
        <p className="text-[13px]">{message}</p>
        <div className="flex justify-start gap-1">
          <Button size="sm" variant="primary" onClick={() => markLearned(id)}>
            Hide
          </Button>
        </div>
      </PopoverContent>
    </Popover>
  );
}
