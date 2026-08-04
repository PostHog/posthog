import { useHostTRPC } from "@posthog/host-router/react";
import { Skeleton } from "@radix-ui/themes";
import { useQuery } from "@tanstack/react-query";

function formatSize(bytes: number): string {
  if (bytes === 0) return "0 B";
  const units = ["B", "KB", "MB", "GB"];
  const i = Math.min(
    units.length - 1,
    Math.floor(Math.log(bytes) / Math.log(1024)),
  );
  const size = bytes / 1024 ** i;
  return `${size.toFixed(i > 1 ? 1 : 0)} ${units[i]}`;
}

interface WorktreeSizeProps {
  worktreePath: string;
}

export function WorktreeSize({ worktreePath }: WorktreeSizeProps) {
  const trpc = useHostTRPC();
  const { data, isLoading } = useQuery(
    trpc.workspace.getWorktreeSize.queryOptions(
      { worktreePath },
      { staleTime: 60_000 },
    ),
  );

  if (isLoading) {
    return (
      <>
        {" - "}
        <Skeleton className="inline-block h-[12px] w-[50px]" />
      </>
    );
  }

  if (!data) return null;

  return <> - {formatSize(data.sizeBytes)}</>;
}
