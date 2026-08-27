import { useHostTRPC } from "@posthog/host-router/react";
import { useQuery } from "@tanstack/react-query";
import { useMemo } from "react";

export function useSuspendedTaskIds(): Set<string> {
  const trpc = useHostTRPC();
  const { data } = useQuery(trpc.suspension.suspendedTaskIds.queryOptions());
  return useMemo(() => new Set(data ?? []), [data]);
}
