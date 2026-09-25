import type { TaskRunPreviewSession } from "@posthog/shared/domain-types";

export type PreviewSessionState = {
  data: TaskRunPreviewSession | undefined;
  isLoading: boolean;
  isError: boolean;
  isFetching: boolean;
};

export function localPreviewSession(port: number): PreviewSessionState {
  return {
    data: { outcome: "ready", url: `http://localhost:${port}/` },
    isLoading: false,
    isError: false,
    isFetching: false,
  };
}
