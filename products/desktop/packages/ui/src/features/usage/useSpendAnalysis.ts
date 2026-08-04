import type { SpendAnalysisResponse } from "@posthog/api-client/spend-analysis";
import {
  type SpendAnalysisWindow,
  windowToDateFrom,
} from "@posthog/core/billing/spendAnalysisFormat";
import { useOptionalAuthenticatedClient } from "@posthog/ui/features/auth/authClient";
import { logger } from "@posthog/ui/shell/logger";
import { useQuery } from "@tanstack/react-query";

const log = logger.scope("spend-analysis");

const SPEND_ANALYSIS_STALE_TIME_MS = 60_000;

interface UseSpendAnalysisOptions {
  window: SpendAnalysisWindow;
  product?: string;
}

interface UseSpendAnalysisReturn {
  data: SpendAnalysisResponse | null;
  isLoading: boolean;
  isFetching: boolean;
  error: string | null;
  refetch: () => void;
}

export function useSpendAnalysis({
  window,
  product,
}: UseSpendAnalysisOptions): UseSpendAnalysisReturn {
  const client = useOptionalAuthenticatedClient();
  const query = useQuery({
    queryKey: ["billing", "spend-analysis", window, product ?? "all"],
    queryFn: async (): Promise<SpendAnalysisResponse> => {
      if (!client) throw new Error("Not authenticated");
      try {
        return await client.getPersonalSpendAnalysis({
          dateFrom: windowToDateFrom(window),
          product,
        });
      } catch (err) {
        const message = err instanceof Error ? err.message : "Unknown error";
        log.warn("Failed to fetch spend analysis", { error: message });
        throw err;
      }
    },
    enabled: client !== null,
    staleTime: SPEND_ANALYSIS_STALE_TIME_MS,
  });

  return {
    data: query.data ?? null,
    // Not isPending: it stays true forever while the query is disabled pre-auth.
    isLoading: query.isLoading,
    isFetching: query.isFetching,
    error: query.error instanceof Error ? query.error.message : null,
    refetch: () => {
      void query.refetch();
    },
  };
}
