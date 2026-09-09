import { WarningIcon } from "@phosphor-icons/react";
import { Button } from "@posthog/quill";
import type { SketchpadFrameHealth } from "@posthog/ui/features/sketchpad/components/SketchpadFrame";
import type { ReactElement } from "react";

interface SketchpadHealthNoticeProps {
  health: SketchpadFrameHealth;
  stopped: boolean;
  onStop: () => void;
  onStart: () => void;
}

export function SketchpadHealthNotice({
  health,
  stopped,
  onStop,
  onStart,
}: SketchpadHealthNoticeProps): ReactElement | null {
  if (!stopped && health === "running") return null;

  const title = stopped
    ? "This board is stopped"
    : "This board stopped answering";
  const hint = stopped
    ? "Review its code before you start it. Fragments can read data with your PostHog access."
    : "A fragment on it is busy. Stop the board, then start it again.";

  return (
    <div className="pointer-events-none absolute inset-x-0 top-3 z-30 flex justify-center">
      <div className="pointer-events-auto flex max-w-[min(92%,30rem)] items-start gap-2.5 rounded-lg border border-(--gray-6) bg-(--gray-1) px-3.5 py-2.5 shadow-lg">
        <WarningIcon
          weight="fill"
          className="mt-0.5 size-3.5 shrink-0 text-(--amber-9)"
        />
        <div className="min-w-0 space-y-1">
          <p className="font-medium text-(--gray-12) text-[12px]">{title}</p>
          <p className="text-(--gray-11) text-[12px]">{hint}</p>
        </div>
        <Button
          data-attr={stopped ? "sketchpad-start-board" : "sketchpad-stop-board"}
          variant={stopped ? "primary" : "outline"}
          size="sm"
          className="ml-1 shrink-0"
          onClick={stopped ? onStart : onStop}
        >
          {stopped ? "Start the board" : "Stop the board"}
        </Button>
      </div>
    </div>
  );
}
