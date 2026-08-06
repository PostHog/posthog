import { useHostTRPC } from "@posthog/host-router/react";
import { useQuery } from "@tanstack/react-query";

/** Recent Claude Code CLI sessions in ~/.claude for the selected repo. */
export function useClaudeCliSessions(
  repoPath: string | null | undefined,
  enabled: boolean,
) {
  const trpc = useHostTRPC();
  return useQuery(
    trpc.claudeCliSessions.list.queryOptions(
      { repoPath: repoPath ?? "" },
      {
        enabled: enabled && !!repoPath,
        staleTime: 30_000,
        // Local IPC call — never gate it on navigator.onLine.
        networkMode: "always",
      },
    ),
  );
}
