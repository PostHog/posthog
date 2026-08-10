import type { PostHogAPIClient } from "@posthog/api-client/posthog-client";
import { useOptionalAuthenticatedClient } from "@posthog/ui/features/auth/authClient";
import type {
  UseMutationOptions,
  UseMutationResult,
} from "@tanstack/react-query";
import { useMutation } from "@tanstack/react-query";

type AuthenticatedMutationFn<TVariables, TData> = (
  client: PostHogAPIClient,
  variables: TVariables,
) => Promise<TData>;

export function useAuthenticatedMutation<
  TData = unknown,
  TError = Error,
  TVariables = void,
>(
  mutationFn: AuthenticatedMutationFn<TVariables, TData>,
  options?: Omit<UseMutationOptions<TData, TError, TVariables>, "mutationFn">,
): UseMutationResult<TData, TError, TVariables> {
  const client = useOptionalAuthenticatedClient();

  return useMutation({
    mutationFn: async (variables: TVariables) => {
      if (!client) throw new Error("Not authenticated");
      return await mutationFn(client, variables);
    },
    ...options,
  });
}
