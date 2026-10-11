import { useHostTRPC } from "@posthog/host-router/react";
import type { PrPipelineStatus } from "@posthog/shared";
import { PR_PIPELINE_METADATA_FIELDS } from "@posthog/ui/features/sidebar/listItemAppearance";
import { useSidebarStore } from "@posthog/ui/features/sidebar/sidebarStore";
import type { SidebarPrState } from "@posthog/ui/features/sidebar/useTaskPrStatus";
import { useQuery } from "@tanstack/react-query";

/** While something moves, a row keeps up with it. Otherwise it checks rarely. */
const ACTIVE_REFETCH_MS = 60_000;
const IDLE_REFETCH_MS = 5 * 60_000;

function isActive(status: PrPipelineStatus | null | undefined): boolean {
  if (!status) return false;
  return (
    status.ci?.state === "running" ||
    status.mergeQueue === "queuing" ||
    status.mergeQueue === "queued" ||
    status.mergeQueue === "testing"
  );
}

/**
 * CI and merge queue state for a session's PR, for its list row. It is a gh
 * call per row, so it only runs when the reader shows one of these fields and
 * the PR can still change: a merged or closed PR has nothing left to report.
 */
export function usePrPipelineStatus({
  prUrl,
  prState,
  enabled = true,
}: {
  prUrl: string | null | undefined;
  prState: SidebarPrState | undefined;
  enabled?: boolean;
}): PrPipelineStatus | null {
  const trpc = useHostTRPC();
  const wantsPipeline = useSidebarStore((state) =>
    state.listItemMetadataFields.some((field) =>
      PR_PIPELINE_METADATA_FIELDS.includes(field),
    ),
  );
  const settled = prState === "merged" || prState === "closed";
  const shouldFetch = enabled && wantsPipeline && !!prUrl && !settled;

  const { data } = useQuery({
    ...trpc.git.getPrPipelineStatus.queryOptions({ prUrl: prUrl ?? "" }),
    enabled: shouldFetch,
    staleTime: 30_000,
    refetchInterval: (query) =>
      isActive(query.state.data) ? ACTIVE_REFETCH_MS : IDLE_REFETCH_MS,
    retry: 1,
  });

  if (!wantsPipeline || !prUrl || settled) return null;
  // Disabled rows (a drag preview) still read what the live row cached.
  return data ?? null;
}
