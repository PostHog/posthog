import { TWIG_CLOUD_MODE_FLAG } from "@posthog/shared";
import { useHostCapabilities } from "@posthog/ui/shell/useHostCapabilities";
import { useFeatureFlag } from "../../feature-flags/useFeatureFlag";

export function useCloudModeEnabled(): boolean {
  // Cloud mode is always on for cloud-only hosts (web).
  const { localWorkspaces } = useHostCapabilities();
  return (
    useFeatureFlag(TWIG_CLOUD_MODE_FLAG) ||
    import.meta.env.DEV ||
    !localWorkspaces
  );
}
