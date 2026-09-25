import type { ComponentType } from "react";

export type TaskPreviewFrameProps = {
  url: string;
  title: string;
  onLoadFailed: () => void;
};

export type TaskPreviewFrameComponent = ComponentType<TaskPreviewFrameProps>;

export const TASK_PREVIEW_FRAME_COMPONENT = Symbol.for(
  "posthog.ui.TaskPreviewFrameComponent",
);
