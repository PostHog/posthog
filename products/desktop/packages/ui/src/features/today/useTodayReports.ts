import { buildSuggestedReviewerFilterParam } from "@posthog/core/inbox/reportFiltering";
import type { SignalReport } from "@posthog/shared/types";
import { useOptionalAuthenticatedClient } from "@posthog/ui/features/auth/authClient";
import { useCurrentUser } from "@posthog/ui/features/auth/useCurrentUser";
import { useInboxReports } from "@posthog/ui/features/inbox/hooks/useInboxReports";

const TODAY_REPORT_LIMIT = 5;

/** The ready Self-driving reports that name the signed-in user as a reviewer, heaviest first. */
export function useTodayReports(enabled: boolean): {
  reports: SignalReport[] | null;
  totalCount: number;
} {
  const client = useOptionalAuthenticatedClient();
  const { data: currentUser } = useCurrentUser({ client, enabled });
  const reviewerUuid = currentUser?.uuid ?? null;
  const query = useInboxReports(
    {
      status: "ready",
      ordering: "-total_weight",
      limit: TODAY_REPORT_LIMIT,
      suggested_reviewers: reviewerUuid
        ? buildSuggestedReviewerFilterParam([reviewerUuid])
        : undefined,
    },
    { enabled: enabled && reviewerUuid !== null, refetchInterval: 60_000 },
  );
  return {
    reports: query.data?.results ?? null,
    totalCount: query.data?.count ?? 0,
  };
}
