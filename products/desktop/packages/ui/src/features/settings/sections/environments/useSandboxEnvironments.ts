import type { SandboxEnvironmentInput } from "@posthog/shared/domain-types";
import { useQueryClient } from "@tanstack/react-query";
import { useAuthenticatedMutation } from "../../../../hooks/useAuthenticatedMutation";
import { useAuthenticatedQuery } from "../../../../hooks/useAuthenticatedQuery";
import { toast } from "../../../../primitives/toast";

export const sandboxEnvKeys = {
  list: ["sandbox-environments", "list"] as const,
};

export function useSandboxEnvironments() {
  const queryClient = useQueryClient();

  const { data: environments, isLoading } = useAuthenticatedQuery(
    sandboxEnvKeys.list,
    (client) => client.listSandboxEnvironments(),
  );

  const createMutation = useAuthenticatedMutation(
    (client, input: SandboxEnvironmentInput) =>
      client.createSandboxEnvironment(input),
    {
      onSuccess: () => {
        toast.success("Environment created");
        queryClient.invalidateQueries({ queryKey: sandboxEnvKeys.list });
      },
      onError: (error: Error) => {
        toast.error(error.message || "Failed to create environment");
      },
    },
  );

  const updateMutation = useAuthenticatedMutation(
    (
      client,
      { id, ...input }: { id: string } & Partial<SandboxEnvironmentInput>,
    ) => client.updateSandboxEnvironment(id, input),
    {
      onSuccess: () => {
        toast.success("Environment updated");
        queryClient.invalidateQueries({ queryKey: sandboxEnvKeys.list });
      },
      onError: (error: Error) => {
        toast.error(error.message || "Failed to update environment");
      },
    },
  );

  const deleteMutation = useAuthenticatedMutation(
    (client, id: string) => client.deleteSandboxEnvironment(id),
    {
      onSuccess: () => {
        toast.success("Environment deleted");
        queryClient.invalidateQueries({ queryKey: sandboxEnvKeys.list });
      },
      onError: (error: Error) => {
        toast.error(error.message || "Failed to delete environment");
      },
    },
  );

  return {
    environments: environments ?? [],
    isLoading,
    createMutation,
    updateMutation,
    deleteMutation,
  };
}
