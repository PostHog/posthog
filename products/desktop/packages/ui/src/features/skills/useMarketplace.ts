import { useHostTRPC } from "@posthog/host-router/react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

/** Compact install-count formatting shared by the marketplace surfaces. */
export const installsFormatter = new Intl.NumberFormat(undefined, {
  notation: "compact",
});

export interface MarketplaceSkillSummary {
  id: string;
  skillId: string;
  name: string;
  installs: number;
  source: string;
  installed: boolean;
}

export function useMarketplaceSearch(query: string) {
  const trpc = useHostTRPC();
  return useQuery(
    trpc.skills.marketplace.search.queryOptions(
      { query },
      { enabled: query.trim().length >= 2, staleTime: 60_000 },
    ),
  );
}

export function useMarketplacePreview(
  ref: { source: string; skillId: string } | null,
) {
  const trpc = useHostTRPC();
  return useQuery(
    trpc.skills.marketplace.preview.queryOptions(
      { source: ref?.source ?? "", skillId: ref?.skillId ?? "" },
      { enabled: ref !== null, staleTime: 5 * 60_000 },
    ),
  );
}

export function useInstallMarketplaceSkill() {
  const trpc = useHostTRPC();
  const queryClient = useQueryClient();
  return useMutation(
    trpc.skills.marketplace.install.mutationOptions({
      onSuccess: () => {
        void queryClient.invalidateQueries(trpc.skills.pathFilter());
      },
    }),
  );
}
