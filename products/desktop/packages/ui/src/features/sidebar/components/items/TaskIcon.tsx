import {
  Binoculars,
  Broadcast,
  Bug,
  ChatCircle,
  Cloud as CloudIcon,
  FilmSlate,
  Flask,
  GitBranch,
  GitMerge,
  GitPullRequest,
  HandPalm,
  Lifebuoy,
  Pause,
  PushPin,
  Robot,
  SlackLogo,
  WarningCircle,
} from "@phosphor-icons/react";
import type { WorkspaceMode } from "@posthog/shared";
import {
  isTerminalStatus,
  type TaskRunStatus,
} from "@posthog/shared/domain-types";
import { DotsCircleSpinner } from "../../../../primitives/DotsCircleSpinner";
import { NestedButton } from "../../../../primitives/NestedButton";
import { Tooltip } from "../../../../primitives/Tooltip";
import { openExternalUrl } from "../../../../shell/openExternal";
import type { SidebarPrState } from "../../useTaskPrStatus";

export const ICON_SIZE = 12;

// Colors are passed as the phosphor `color` prop (an SVG `fill` attribute)
// rather than `text-*` classes: in the command palette, quill's
// `[data-highlighted] *` rule resets every descendant CSS `color` for the
// selected row, which turns a `currentColor` icon black on hover. An explicit
// `fill` is immune, and renders identically in the sidebar.

// Map origin_product values to the icon + label used to brand the task's
// status icon, so every non-`user_created` origin is distinguishable at a
// glance in the list. `user_created` is intentionally absent — those tasks get
// the default status icon. Extend this when a new origin needs its own badge.
type OriginProductMeta = { Icon: typeof SlackLogo; label: string };
const ORIGIN_PRODUCT_META: Record<string, OriginProductMeta> = {
  slack: { Icon: SlackLogo, label: "Slack" },
  signal_report: { Icon: Broadcast, label: "Signals" },
  signals_scout: { Icon: Binoculars, label: "Signals scout" },
  support_queue: { Icon: Lifebuoy, label: "Support" },
  session_summaries: { Icon: FilmSlate, label: "Session summary" },
  error_tracking: { Icon: Bug, label: "Error tracking" },
  eval_clusters: { Icon: Flask, label: "Evals" },
  automation: { Icon: Robot, label: "Automation" },
};

export function getOriginProductMeta(
  originProduct?: string,
): OriginProductMeta | undefined {
  return originProduct ? ORIGIN_PRODUCT_META[originProduct] : undefined;
}

// Renders the icon inside a span. When `link` is set the icon becomes a
// clickable NestedButton that opens the originating thread externally.
// SidebarItem renders the row as a `<button>`, so a real `<a>` or a nested
// `<button>` here would be invalid HTML.
function IconSpan({
  icon,
  link,
  ariaLabel,
}: {
  icon: React.ReactNode;
  link?: string;
  ariaLabel?: string;
}) {
  if (!link) {
    if (!ariaLabel) {
      return <span className="flex items-center justify-center">{icon}</span>;
    }
    return (
      <span
        aria-label={ariaLabel}
        className="flex items-center justify-center"
        role="img"
      >
        {icon}
      </span>
    );
  }
  return (
    <NestedButton
      aria-label={ariaLabel}
      className="flex cursor-pointer items-center justify-center rounded transition-opacity hover:opacity-70"
      onActivate={() => {
        openExternalUrl(link);
      }}
    >
      {icon}
    </NestedButton>
  );
}

function CloudStatusIcon({
  taskRunStatus,
  originProduct,
  threadUrl,
  size,
}: {
  taskRunStatus?: TaskRunStatus;
  originProduct?: string;
  threadUrl?: string;
  size: number;
}) {
  const meta = getOriginProductMeta(originProduct);
  const Icon = meta?.Icon ?? CloudIcon;
  const sourceLabel = meta?.label ?? "Cloud";
  const link = meta && threadUrl ? threadUrl : undefined;
  const ariaLabel = link ? `Open ${sourceLabel} thread` : undefined;

  if (taskRunStatus === "queued") {
    return (
      <Tooltip
        content={
          link ? `Open ${sourceLabel} thread` : `${sourceLabel} (queued)`
        }
        side="right"
      >
        <IconSpan
          icon={<Icon size={size} className="ph-pulse" />}
          link={link}
          ariaLabel={ariaLabel}
        />
      </Tooltip>
    );
  }
  if (taskRunStatus === "in_progress") {
    return (
      <Tooltip
        content={
          link ? `Open ${sourceLabel} thread` : `${sourceLabel} (running)`
        }
        side="right"
      >
        <IconSpan
          icon={<Icon size={size} weight="fill" color="var(--accent-11)" />}
          link={link}
          ariaLabel={ariaLabel}
        />
      </Tooltip>
    );
  }
  if (taskRunStatus === "completed") {
    return (
      <Tooltip
        content={
          link ? `Open ${sourceLabel} thread` : `${sourceLabel} (completed)`
        }
        side="right"
      >
        <IconSpan
          icon={<Icon size={size} weight="fill" color="var(--green-11)" />}
          link={link}
          ariaLabel={ariaLabel}
        />
      </Tooltip>
    );
  }
  if (taskRunStatus === "cancelled") {
    return (
      <Tooltip
        content={
          link ? `Open ${sourceLabel} thread` : `${sourceLabel} (stopped)`
        }
        side="right"
      >
        <IconSpan
          icon={<Icon size={size} weight="fill" color="var(--green-11)" />}
          link={link}
          ariaLabel={
            link
              ? `Open ${sourceLabel} thread (stopped)`
              : `${sourceLabel} (stopped)`
          }
        />
      </Tooltip>
    );
  }
  if (taskRunStatus === "failed") {
    return (
      <Tooltip
        content={
          link ? `Open ${sourceLabel} thread` : `${sourceLabel} (failed)`
        }
        side="right"
      >
        <IconSpan
          icon={<Icon size={size} weight="fill" color="var(--red-11)" />}
          link={link}
          ariaLabel={ariaLabel}
        />
      </Tooltip>
    );
  }
  return (
    <Tooltip
      content={link ? `Open ${sourceLabel} thread` : sourceLabel}
      side="right"
    >
      <IconSpan icon={<Icon size={size} />} link={link} ariaLabel={ariaLabel} />
    </Tooltip>
  );
}

function PrStatusIcon({
  prState,
  hasDiff,
  size,
}: {
  prState?: SidebarPrState;
  hasDiff?: boolean;
  size: number;
}) {
  if (prState === "merged") {
    return (
      <Tooltip content="PR merged" side="right">
        <span className="flex items-center justify-center">
          <GitMerge size={size} weight="bold" color="var(--purple-11)" />
        </span>
      </Tooltip>
    );
  }
  if (prState === "open") {
    return (
      <Tooltip content="PR open" side="right">
        <span className="flex items-center justify-center">
          <GitPullRequest size={size} weight="bold" color="var(--green-11)" />
        </span>
      </Tooltip>
    );
  }
  if (prState === "draft") {
    return (
      <Tooltip content="Draft PR" side="right">
        <span className="flex items-center justify-center">
          <GitPullRequest size={size} weight="bold" color="var(--gray-9)" />
        </span>
      </Tooltip>
    );
  }
  if (prState === "closed") {
    return (
      <Tooltip content="PR closed" side="right">
        <span className="flex items-center justify-center">
          <GitPullRequest size={size} weight="bold" color="var(--red-11)" />
        </span>
      </Tooltip>
    );
  }
  if (hasDiff) {
    return (
      <Tooltip content="Has changes" side="right">
        <span className="flex items-center justify-center">
          <GitBranch size={size} weight="bold" color="var(--amber-11)" />
        </span>
      </Tooltip>
    );
  }
  return null;
}

export interface TaskIconProps {
  workspaceMode?: WorkspaceMode;
  isGenerating?: boolean;
  isUnread?: boolean;
  isPinned?: boolean;
  isSuspended?: boolean;
  needsPermission?: boolean;
  taskRunStatus?: TaskRunStatus;
  originProduct?: string;
  /** Pre-built URL to the originating Slack thread (read from
   * `task.latest_run.state.slack_thread_url`). When set, the Slack icon
   * becomes a link that opens the thread in the user's browser. */
  slackThreadUrl?: string;
  prState?: SidebarPrState;
  hasDiff?: boolean;
  size?: number;
}

/**
 * Status icon for a task, shared by the sidebar task list and the command
 * palette so both render the exact same states (cloud run status, PR/branch
 * status, generating, unread, etc.).
 */
export function TaskIcon({
  workspaceMode,
  isGenerating,
  isUnread,
  isPinned,
  isSuspended,
  needsPermission,
  taskRunStatus,
  originProduct,
  slackThreadUrl,
  prState,
  hasDiff,
  size = ICON_SIZE,
}: TaskIconProps) {
  const isCloudTask = workspaceMode === "cloud";
  const isTerminalCloud = isCloudTask && isTerminalStatus(taskRunStatus);
  const originProductMeta = getOriginProductMeta(originProduct);

  if (needsPermission) {
    return (
      <Tooltip content="Needs permission" side="right">
        <span className="flex items-center justify-center">
          <HandPalm size={size} color="var(--blue-11)" />
        </span>
      </Tooltip>
    );
  }
  if (isGenerating) {
    return <DotsCircleSpinner size={size} className="text-accent-11" />;
  }
  // Unread outranks the cloud/PR/diff status icons: when an agent finishes a
  // task there is fresh activity the user has not seen, and that "needs
  // attention" signal must win over the completed-cloud or PR icon that would
  // otherwise hide it. Viewing the task clears `isUnread`, so the normal status
  // icon returns automatically.
  if (isUnread) {
    return (
      <Tooltip content="Unread — new activity" side="right">
        <span className="flex items-center justify-center">
          <WarningCircle size={size} weight="fill" color="var(--amber-11)" />
        </span>
      </Tooltip>
    );
  }
  if (isTerminalCloud) {
    return (
      <CloudStatusIcon
        taskRunStatus={taskRunStatus}
        originProduct={originProduct}
        threadUrl={slackThreadUrl}
        size={size}
      />
    );
  }
  if (isSuspended) {
    return (
      <Tooltip content="Suspended" side="right">
        <span className="flex items-center justify-center">
          <Pause size={size} color="var(--gray-9)" />
        </span>
      </Tooltip>
    );
  }
  if (prState || hasDiff) {
    return <PrStatusIcon prState={prState} hasDiff={hasDiff} size={size} />;
  }
  if (isPinned) {
    return <PushPin size={size} color="var(--accent-11)" />;
  }
  if (isCloudTask) {
    return (
      <CloudStatusIcon
        taskRunStatus={taskRunStatus}
        originProduct={originProduct}
        threadUrl={slackThreadUrl}
        size={size}
      />
    );
  }
  if (originProductMeta) {
    const { Icon, label } = originProductMeta;
    const link = slackThreadUrl;
    return (
      <Tooltip
        content={link ? `Open ${label} thread` : `From ${label}`}
        side="right"
      >
        <IconSpan
          icon={<Icon size={size} color="var(--gray-10)" />}
          link={link}
          ariaLabel={`Open ${label} thread`}
        />
      </Tooltip>
    );
  }
  return <ChatCircle size={size} color="var(--gray-10)" />;
}
