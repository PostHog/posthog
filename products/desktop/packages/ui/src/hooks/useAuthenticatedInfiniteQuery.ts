import type { PostHogAPIClient } from "@posthog/api-client/posthog-client";
import { useOptionalAuthenticatedClient } from "@posthog/ui/features/auth/authClient";
import { AUTH_SCOPED_QUERY_META } from "@posthog/ui/features/auth/useCurrentUser";
import type { QueryKey } from "@tanstack/react-query";
import { useInfiniteQuery } from "@tanstack/react-query";

type AuthenticatedInfiniteQueryFn<TData, TPageParam> = (
  client: PostHogAPIClient,
  pageParam: TPageParam,
) => Promise<TData>;

interface UseAuthenticatedInfiniteQueryOptions<TData, TPageParam> {
  enabled?: boolean;
  getNextPageParam: (
    lastPage: TData,
    allPages: TData[],
  ) => TPageParam | undefined;
  initialPageParam: TPageParam;
  refetchInterval?:
    | number
    | false
    | (() => number | false | undefined)
    | ((query: unknown) => number | false | undefined);
  refetchIntervalInBackground?: boolean;
  staleTime?: number;
}

export function useAuthenticatedInfiniteQuery<
  TData,
  TPageParam,
  TQueryKey extends QueryKey = QueryKey,
>(
  queryKey: TQueryKey,
  queryFn: AuthenticatedInfiniteQueryFn<TData, TPageParam>,
  options: UseAuthenticatedInfiniteQueryOptions<TData, TPageParam>,
) {
  const client = useOptionalAuthenticatedClient();

  return useInfiniteQuery({
    queryKey,
    queryFn: async ({ pageParam }) => {
      if (!client) throw new Error("Not authenticated");
      return await queryFn(client, pageParam as TPageParam);
    },
    enabled: !!client && (options.enabled ?? true),
    getNextPageParam: options.getNextPageParam,
    initialPageParam: options.initialPageParam,
    refetchInterval: options.refetchInterval,
    refetchIntervalInBackground: options.refetchIntervalInBackground,
    staleTime: options.staleTime,
    meta: AUTH_SCOPED_QUERY_META,
  });
}
