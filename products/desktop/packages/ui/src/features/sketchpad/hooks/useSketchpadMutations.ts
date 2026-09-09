import { useHostTRPC } from "@posthog/host-router/react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

export function useSketchpadMutations() {
  const trpc = useHostTRPC();
  const queryClient = useQueryClient();

  const invalidate = () => {
    void queryClient.invalidateQueries(trpc.sketchpad.list.pathFilter());
  };

  const create = useMutation(
    trpc.sketchpad.create.mutationOptions({ onSuccess: invalidate }),
  );
  const update = useMutation(
    trpc.sketchpad.update.mutationOptions({ onSuccess: invalidate }),
  );
  const remove = useMutation(
    trpc.sketchpad.remove.mutationOptions({ onSuccess: invalidate }),
  );

  return {
    createSketchpad: (channelId: string, name: string) =>
      create.mutateAsync({ channelId, name }),
    renameSketchpad: (id: string, name: string) =>
      update.mutateAsync({ id, patch: { name } }),
    fileSketchpad: (id: string, channelId: string) =>
      update.mutateAsync({ id, patch: { channelId } }),
    setSketchpadPinned: (id: string, pinned: boolean) =>
      update.mutateAsync({ id, patch: { pinned } }),
    removeSketchpad: (id: string) => remove.mutateAsync({ id }),
    isCreating: create.isPending,
    isRenaming: update.isPending && update.variables.patch.name !== undefined,
  };
}
