import { useHostTRPC } from "@posthog/host-router/react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useCallback } from "react";

function useInvalidateSkills() {
  const trpc = useHostTRPC();
  const queryClient = useQueryClient();
  return useCallback(() => {
    void queryClient.invalidateQueries(trpc.skills.pathFilter());
  }, [queryClient, trpc]);
}

export function useCreateSkill() {
  const trpc = useHostTRPC();
  const invalidate = useInvalidateSkills();
  return useMutation(
    trpc.skills.create.mutationOptions({ onSuccess: invalidate }),
  );
}

export function useSaveSkillManifest() {
  const trpc = useHostTRPC();
  const invalidate = useInvalidateSkills();
  return useMutation(
    trpc.skills.saveManifest.mutationOptions({ onSuccess: invalidate }),
  );
}

export function useSaveSkillFile() {
  const trpc = useHostTRPC();
  const invalidate = useInvalidateSkills();
  return useMutation(
    trpc.skills.saveFile.mutationOptions({ onSuccess: invalidate }),
  );
}

export function useRenameSkillFile() {
  const trpc = useHostTRPC();
  const invalidate = useInvalidateSkills();
  return useMutation(
    trpc.skills.renameFile.mutationOptions({ onSuccess: invalidate }),
  );
}

export function useDeleteSkillFile() {
  const trpc = useHostTRPC();
  const invalidate = useInvalidateSkills();
  return useMutation(
    trpc.skills.deleteFile.mutationOptions({ onSuccess: invalidate }),
  );
}

export function useDeleteSkill() {
  const trpc = useHostTRPC();
  const invalidate = useInvalidateSkills();
  return useMutation(
    trpc.skills.delete.mutationOptions({ onSuccess: invalidate }),
  );
}

export function useImportCodexSkill() {
  const trpc = useHostTRPC();
  const invalidate = useInvalidateSkills();
  return useMutation(
    trpc.skills.importCodex.mutationOptions({ onSuccess: invalidate }),
  );
}
