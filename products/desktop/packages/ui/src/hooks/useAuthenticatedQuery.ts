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
    // After the caller's options, so a caller passing its own `enabled` can't drop the
    // client gate. Without it the query fires before the client exists, throws
    // "Not authenticated", and sits out its retry backoffs before it can succeed.
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
