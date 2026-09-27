import { useServiceOptional } from "@posthog/di/react";
import { cn } from "@posthog/quill";
import { WEB_PAGE_BACKGROUND } from "./pageBackground";
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
      className={cn("size-full border-0", WEB_PAGE_BACKGROUND)}
      sandbox="allow-scripts allow-same-origin allow-forms allow-popups allow-modals"
      referrerPolicy="no-referrer"
      onLoad={() => props.onLoadingChange(false)}
    />
  );
}
