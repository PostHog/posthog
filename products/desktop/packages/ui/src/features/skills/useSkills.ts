import { useHostTRPC } from "@posthog/host-router/react";
import { useQuery } from "@tanstack/react-query";

export function useSkills() {
  const trpc = useHostTRPC();
  return useQuery(trpc.skills.list.queryOptions());
}
