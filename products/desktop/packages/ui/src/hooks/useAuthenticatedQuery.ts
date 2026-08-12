import type { PostHogAPIClient } from "@posthog/api-client/posthog-client";
import { useOptionalAuthenticatedClient } from "@posthog/ui/features/auth/authClient";
import { AUTH_SCOPED_QUERY_META } from "@posthog/ui/features/auth/useCurrentUser";
import type {
  QueryKey,
  UseQueryOptions,
  UseQueryResult,
} from "@tanstack/react-query";
import { useQuery } from "@tanstack/react-query";

type AuthenticatedQueryFn<T> = (client: PostHogAPIClient) => Promise<T>;

export function useAuthenticatedQuery<
  TData = unknown,
  TError = Error,
  TQueryKey extends QueryKey = QueryKey,
>(
  queryKey: TQueryKey,
  queryFn: AuthenticatedQueryFn<TData>,
  options?: Omit<
    UseQueryOptions<TData, TError, TData, TQueryKey>,
    "queryKey" | "queryFn"
  >,
): UseQueryResult<TData, TError> {
  const client = useOptionalAuthenticatedClient();
  const { meta, enabled, ...restOptions } = options ?? {};

  return useQuery({
    queryKey,
    queryFn: async () => {
      if (!client) throw new Error("Not authenticated");
      return await queryFn(client);
    },
    ...restOptions,
    // After the caller's options, not before: spreading them last used to drop this gate
    // for every caller that passes its own `enabled`. Such a query fired before the client
    // existed, threw "Not authenticated", and then sat out three retry backoffs — seconds
    // of a loading state for data that was one round trip away.
    enabled:
      typeof enabled === "function"
        ? (query) => !!client && enabled(query)
        : !!client && (enabled ?? true),
    meta: {
      ...AUTH_SCOPED_QUERY_META,
      ...meta,
    },
  });
}
