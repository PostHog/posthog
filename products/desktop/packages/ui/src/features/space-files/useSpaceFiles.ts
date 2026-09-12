import type {
  SpaceFile,
  SpaceFileCreate,
  SpaceFileSummary,
} from "@posthog/api-client/posthog-client";
import { useOptionalAuthenticatedClient } from "@posthog/ui/features/auth/authClient";
import { AUTH_SCOPED_QUERY_META } from "@posthog/ui/features/auth/useCurrentUser";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

export const SPACE_FILES_QUERY_KEY = ["space-files"] as const;

export function spaceFileQueryKey(id: string): readonly string[] {
  return [...SPACE_FILES_QUERY_KEY, id];
}

export function useSpaceFiles(): {
  files: SpaceFileSummary[];
  isLoading: boolean;
  isError: boolean;
  error: Error | null;
  reload: () => Promise<void>;
} {
  const client = useOptionalAuthenticatedClient();
  const query = useQuery({
    queryKey: SPACE_FILES_QUERY_KEY,
    queryFn: async () => {
      if (!client) throw new Error("Not authenticated");
      return await client.listSpaceFiles();
    },
    enabled: !!client,
    meta: AUTH_SCOPED_QUERY_META,
  });

  return {
    files: query.data ?? [],
    isLoading: query.isLoading,
    isError: query.isError,
    error: query.error,
    reload: async () => {
      await query.refetch();
    },
  };
}

export function useSpaceFile(id: string | undefined): {
  file: SpaceFile | undefined;
  isLoading: boolean;
  isError: boolean;
  error: Error | null;
  reload: () => Promise<SpaceFile | undefined>;
} {
  const client = useOptionalAuthenticatedClient();
  const query = useQuery({
    queryKey: spaceFileQueryKey(id ?? ""),
    queryFn: async () => {
      if (!client || !id) throw new Error("Not authenticated");
      return await client.getSpaceFile(id);
    },
    enabled: !!client && !!id,
    meta: AUTH_SCOPED_QUERY_META,
  });

  return {
    file: query.data,
    isLoading: query.isLoading,
    isError: query.isError,
    error: query.error,
    reload: async () => await query.refetch().then((result) => result.data),
  };
}

export function useSpaceFileMutations(): {
  create: (input: SpaceFileCreate) => Promise<SpaceFile>;
  update: (
    id: string,
    input: { content: string; baseVersion: number },
  ) => Promise<SpaceFile>;
  isCreating: boolean;
  isUpdating: boolean;
} {
  const client = useOptionalAuthenticatedClient();
  const queryClient = useQueryClient();
  const refreshList = (): void => {
    void queryClient.invalidateQueries({ queryKey: SPACE_FILES_QUERY_KEY });
  };
  const createMutation = useMutation({
    mutationFn: async (input: SpaceFileCreate) => {
      if (!client) throw new Error("Not authenticated");
      return await client.createSpaceFile(input);
    },
    onSuccess: (file) => {
      queryClient.setQueryData(spaceFileQueryKey(file.id), file);
      refreshList();
    },
  });
  const updateMutation = useMutation({
    mutationFn: async ({
      id,
      input,
    }: {
      id: string;
      input: { content: string; baseVersion: number };
    }) => {
      if (!client) throw new Error("Not authenticated");
      return await client.updateSpaceFile(id, input);
    },
    onSuccess: (file) => {
      queryClient.setQueryData(spaceFileQueryKey(file.id), file);
      refreshList();
    },
  });

  return {
    create: (input) => createMutation.mutateAsync(input),
    update: (id, input) => updateMutation.mutateAsync({ id, input }),
    isCreating: createMutation.isPending,
    isUpdating: updateMutation.isPending,
  };
}
