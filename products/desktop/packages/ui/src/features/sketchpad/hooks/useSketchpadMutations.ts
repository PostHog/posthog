import { useHostTRPC } from "@posthog/host-router/react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useCallback, useMemo } from "react";

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

  const createAsync = create.mutateAsync;
  const updateAsync = update.mutateAsync;
  const removeAsync = remove.mutateAsync;
  const createSketchpad = useCallback(
    (channelId: string, name: string) => createAsync({ channelId, name }),
    [createAsync],
  );
  const renameSketchpad = useCallback(
    (id: string, name: string) => updateAsync({ id, patch: { name } }),
    [updateAsync],
  );
  const fileSketchpad = useCallback(
    (id: string, channelId: string) =>
      updateAsync({ id, patch: { channelId } }),
    [updateAsync],
  );
  const setSketchpadPinned = useCallback(
    (id: string, pinned: boolean) => updateAsync({ id, patch: { pinned } }),
    [updateAsync],
  );
  const removeSketchpad = useCallback(
    (id: string) => removeAsync({ id }),
    [removeAsync],
  );
  const isCreating = create.isPending;
  const isRenaming =
    update.isPending && update.variables.patch.name !== undefined;
  return useMemo(
    () => ({
      createSketchpad,
      renameSketchpad,
      fileSketchpad,
      setSketchpadPinned,
      removeSketchpad,
      isCreating,
      isRenaming,
    }),
    [
      createSketchpad,
      renameSketchpad,
      fileSketchpad,
      setSketchpadPinned,
      removeSketchpad,
      isCreating,
      isRenaming,
    ],
  );
}
