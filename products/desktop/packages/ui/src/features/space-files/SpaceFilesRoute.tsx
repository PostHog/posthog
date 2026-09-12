import { SPACE_FILES_FLAG } from "@posthog/shared";
import { useFeatureFlag } from "@posthog/ui/features/feature-flags/useFeatureFlag";
import { SpaceFileDocument } from "@posthog/ui/features/space-files/SpaceFileDocument";
import { useRouterState } from "@tanstack/react-router";
import type { ReactElement } from "react";

export function SpaceFilesRoute(): ReactElement | null {
  const enabled = useFeatureFlag(SPACE_FILES_FLAG);
  const fileId = useRouterState({
    select: (state) => {
      const file = state.location.search.file;
      return typeof file === "string" && file ? file : undefined;
    },
  });
  return enabled ? <SpaceFileDocument id={fileId} /> : null;
}
