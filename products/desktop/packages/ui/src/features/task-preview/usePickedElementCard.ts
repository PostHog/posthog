import type { ElementCommentAnchor } from "@posthog/core/comments/anchors";
import { type RefObject, useCallback, useState } from "react";
import type {
  TaskPreviewElement,
  TaskPreviewRect,
} from "./taskPreviewFrameHost";

export type PickedElement = {
  anchor: ElementCommentAnchor;
  screenshot: string | null;
  position: { top: number; endX: number; bottom: number };
};

export function usePickedElementCard(
  frameRef: RefObject<HTMLDivElement | null>,
  onCommentingChange: (commenting: boolean) => void,
) {
  const [pending, setPending] = useState<PickedElement | null>(null);

  const placeCard = useCallback(
    (rect: TaskPreviewRect) => {
      const box = frameRef.current?.getBoundingClientRect();
      if (!box) return null;
      const clamp = (value: number) =>
        Math.min(Math.max(value, box.top), box.bottom);
      return {
        top: clamp(box.top + rect.top),
        endX: box.left + rect.right,
        bottom: clamp(box.top + rect.bottom),
      };
    },
    [frameRef],
  );

  const onTrackedRect = useCallback(
    (rect: TaskPreviewRect) => {
      const position = placeCard(rect);
      if (!position) return;
      setPending((current) => (current ? { ...current, position } : current));
    },
    [placeCard],
  );

  const onPicked = useCallback(
    (
      element: TaskPreviewElement,
      rect: TaskPreviewRect,
      screenshot: string | null,
    ) => {
      onCommentingChange(false);
      const position = placeCard(rect);
      if (!position) return;
      setPending({
        anchor: { kind: "element", ...element },
        screenshot,
        position,
      });
    },
    [onCommentingChange, placeCard],
  );

  const dismiss = useCallback(() => setPending(null), []);

  return { pending, onPicked, onTrackedRect, dismiss };
}
