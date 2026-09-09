import {
  ArrowsOutIcon,
  BracketsCurlyIcon,
  ChatCircleIcon,
  ClockCounterClockwiseIcon,
  MagnifyingGlassMinusIcon,
  MagnifyingGlassPlusIcon,
  SquaresFourIcon,
} from "@phosphor-icons/react";
import {
  Button,
  Toggle,
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@posthog/quill";
import {
  TOOLBAR_HISTORY,
  TOOLBAR_STATE,
} from "@posthog/ui/features/sketchpad/sketchpadCopy";
import type { ReactElement, ReactNode } from "react";
import type { SketchpadPanelName } from "../interaction/sketchpadViewStore";

interface SketchpadToolbarProps {
  zoom: number;
  activePanel: SketchpadPanelName | null;
  onZoomIn: () => void;
  onZoomOut: () => void;
  onZoomReset: () => void;
  onFitToContent: () => void;
  onPanelChange: (panel: SketchpadPanelName | null) => void;
}

export function SketchpadToolbar({
  zoom,
  activePanel,
  onZoomIn,
  onZoomOut,
  onZoomReset,
  onFitToContent,
  onPanelChange,
}: SketchpadToolbarProps): ReactElement {
  return (
    <TooltipProvider delay={400}>
      <div className="-translate-x-1/2 absolute bottom-4 left-1/2 z-30 flex items-center gap-0.5 rounded-full border border-(--gray-a5) bg-(--gray-1)/85 p-1 shadow-lg backdrop-blur-md">
        <IconAction label="Zoom out" onClick={onZoomOut}>
          <MagnifyingGlassMinusIcon />
        </IconAction>
        <Tooltip>
          <TooltipTrigger
            render={
              <Button
                variant="default"
                size="xs"
                className="min-w-11 rounded-full border-0 bg-transparent font-medium tabular-nums shadow-none hover:bg-(--gray-a3)"
                onClick={onZoomReset}
              >
                {`${Math.round(zoom * 100)}%`}
              </Button>
            }
          />
          <TooltipContent side="top">Reset zoom to 100%</TooltipContent>
        </Tooltip>
        <IconAction label="Zoom in" onClick={onZoomIn}>
          <MagnifyingGlassPlusIcon />
        </IconAction>
        <IconAction label="Fit to content" onClick={onFitToContent}>
          <ArrowsOutIcon />
        </IconAction>

        <div className="mx-1 h-5 w-px bg-(--gray-a5)" />

        <IconToggle
          label="Library"
          pressed={activePanel === "palette"}
          onPressedChange={(pressed) =>
            onPanelChange(pressed ? "palette" : null)
          }
        >
          <SquaresFourIcon />
        </IconToggle>
        <IconToggle
          label="Agent"
          pressed={activePanel === "chat"}
          onPressedChange={(pressed) => onPanelChange(pressed ? "chat" : null)}
        >
          <ChatCircleIcon />
        </IconToggle>
        <IconToggle
          label={TOOLBAR_HISTORY}
          pressed={activePanel === "history"}
          onPressedChange={(pressed) =>
            onPanelChange(pressed ? "history" : null)
          }
        >
          <ClockCounterClockwiseIcon />
        </IconToggle>
        <IconToggle
          label={TOOLBAR_STATE}
          pressed={activePanel === "inspector"}
          onPressedChange={(pressed) =>
            onPanelChange(pressed ? "inspector" : null)
          }
        >
          <BracketsCurlyIcon />
        </IconToggle>
      </div>
    </TooltipProvider>
  );
}

function IconAction({
  label,
  onClick,
  children,
}: {
  label: string;
  onClick: () => void;
  children: ReactNode;
}): ReactElement {
  return (
    <Tooltip>
      <TooltipTrigger
        render={
          <Button
            variant="default"
            size="icon-sm"
            className="rounded-full border-0 bg-transparent shadow-none hover:bg-(--gray-a3)"
            aria-label={label}
            onClick={onClick}
          />
        }
      >
        {children}
      </TooltipTrigger>
      <TooltipContent side="top">{label}</TooltipContent>
    </Tooltip>
  );
}

function IconToggle({
  label,
  pressed,
  onPressedChange,
  children,
}: {
  label: string;
  pressed: boolean;
  onPressedChange: (pressed: boolean) => void;
  children: ReactNode;
}): ReactElement {
  return (
    <Tooltip>
      <TooltipTrigger
        render={
          <Toggle
            size="sm"
            className="rounded-full border-0 bg-transparent shadow-none hover:bg-(--gray-a3) data-pressed:bg-(--gray-a5)"
            aria-label={label}
            pressed={pressed}
            onPressedChange={onPressedChange}
          />
        }
      >
        {children}
      </TooltipTrigger>
      <TooltipContent side="top">{label}</TooltipContent>
    </Tooltip>
  );
}
