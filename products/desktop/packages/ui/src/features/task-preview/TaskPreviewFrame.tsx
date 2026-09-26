import { useServiceOptional } from "@posthog/di/react";
import {
  TASK_PREVIEW_FRAME_COMPONENT,
  type TaskPreviewFrameComponent,
  type TaskPreviewFrameProps,
} from "./taskPreviewFrameHost";

export function TaskPreviewFrame(props: TaskPreviewFrameProps) {
  const HostFrame = useServiceOptional<TaskPreviewFrameComponent>(
    TASK_PREVIEW_FRAME_COMPONENT,
  );
  if (HostFrame) return <HostFrame {...props} />;
  return (
    <iframe
      src={props.url}
      title={props.title}
      className="size-full border-0 bg-white"
      sandbox="allow-scripts allow-same-origin allow-forms allow-popups allow-modals"
      referrerPolicy="no-referrer"
    />
  );
}
