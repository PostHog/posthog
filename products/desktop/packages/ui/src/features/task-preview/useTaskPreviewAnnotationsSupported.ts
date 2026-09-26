import { useServiceOptional } from "@posthog/di/react";
import {
  TASK_PREVIEW_FRAME_COMPONENT,
  type TaskPreviewFrameComponent,
} from "./taskPreviewFrameHost";

export function useTaskPreviewAnnotationsSupported(): boolean {
  return !!useServiceOptional<TaskPreviewFrameComponent>(
    TASK_PREVIEW_FRAME_COMPONENT,
  );
}
