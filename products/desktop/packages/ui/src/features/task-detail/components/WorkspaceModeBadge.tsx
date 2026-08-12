import { Cloud, GitFork, HardDrives } from "@phosphor-icons/react";
import type { WorkspaceMode } from "@posthog/shared";
import { Tooltip } from "../../../primitives/Tooltip";

const MODE_META: Record<
  WorkspaceMode,
  { Icon: typeof Cloud; label: string; color: string }
> = {
  local: {
    Icon: HardDrives,
    label: "Local — runs on your working copy",
    color: "var(--gray-10)",
  },
  worktree: {
    Icon: GitFork,
    label: "Worktree — runs in an isolated git worktree",
    color: "var(--teal-11)",
  },
  cloud: {
    Icon: Cloud,
    label: "Cloud — runs on a remote machine",
    color: "var(--accent-11)",
  },
};

export function WorkspaceModeBadge({
  mode,
  checkoutPath,
}: {
  mode?: WorkspaceMode;
  /** Directory the task runs in, appended to the tooltip for local/worktree tasks. */
  checkoutPath?: string | null;
}) {
  if (!mode) return null;
  const { Icon, label, color } = MODE_META[mode];
  const content =
    mode !== "cloud" && checkoutPath ? (
      <span className="flex flex-col">
        <span>{label}</span>
        <span className="text-gray-10">{checkoutPath}</span>
      </span>
    ) : (
      label
    );
  return (
    <Tooltip content={content} side="bottom" delayDuration={300}>
      <span className="no-drag flex shrink-0 items-center justify-center">
        <Icon size={13} weight="fill" color={color} />
      </span>
    </Tooltip>
  );
}
