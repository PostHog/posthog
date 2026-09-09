import type { SketchpadPoint } from "@posthog/core/sketchpad/sketchpadGeometry";
import type { ReactElement } from "react";

export const SKETCHPAD_DRAG_MIME = "application/x-posthog-sketchpad-fragment";

interface DropCaptureLayerProps {
  active: boolean;
  toWorld: (client: SketchpadPoint) => SketchpadPoint;
  onDropFragment: (name: string, world: SketchpadPoint) => void;
}

export function DropCaptureLayer({
  active,
  toWorld,
  onDropFragment,
}: DropCaptureLayerProps): ReactElement | null {
  if (!active) return null;

  return (
    <section
      aria-label="Drop fragment here"
      className="absolute inset-0 z-20"
      onDragOver={(event) => {
        event.preventDefault();
        event.dataTransfer.dropEffect = "copy";
      }}
      onDrop={(event) => {
        event.preventDefault();
        const name = event.dataTransfer.getData(SKETCHPAD_DRAG_MIME);
        if (!name) return;
        onDropFragment(name, toWorld({ x: event.clientX, y: event.clientY }));
      }}
    />
  );
}
