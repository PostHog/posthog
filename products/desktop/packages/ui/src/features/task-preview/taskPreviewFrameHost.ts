import type { ElementCommentAnchor } from "@posthog/core/comments/anchors";
import type { ComponentType } from "react";

export type TaskPreviewElement = Omit<ElementCommentAnchor, "kind">;

export type TaskPreviewRect = {
  top: number;
  left: number;
  right: number;
  bottom: number;
  width: number;
  height: number;
};

export type TaskPreviewPin = {
  id: string;
  number: number;
  path: string;
  selector: string;
  active: boolean;
};

export type TaskPreviewLocateRequest = { id: string; nonce: number };

export type TaskPreviewFrameProps = {
  url: string;
  title: string;
  picking: boolean;
  pins: TaskPreviewPin[];
  locateRequest: TaskPreviewLocateRequest | null;
  onLoadFailed: () => void;
  onPicked: (
    element: TaskPreviewElement,
    rect: TaskPreviewRect,
    screenshot: string | null,
  ) => void;
  onPickCancelled: () => void;
  onActivatePin: (id: string) => void;
};

export type TaskPreviewFrameComponent = ComponentType<TaskPreviewFrameProps>;

export const TASK_PREVIEW_FRAME_COMPONENT = Symbol.for(
  "posthog.ui.TaskPreviewFrameComponent",
);
