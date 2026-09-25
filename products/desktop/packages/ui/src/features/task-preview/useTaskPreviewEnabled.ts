import { TASK_PORT_PREVIEW_FLAG } from "@posthog/shared";
import { useFeatureFlag } from "../feature-flags/useFeatureFlag";

export function useTaskPreviewEnabled(): boolean {
  return useFeatureFlag(TASK_PORT_PREVIEW_FLAG) || import.meta.env.DEV;
}
