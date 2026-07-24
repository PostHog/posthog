import { Archive, GitPullRequest, PushPin } from "@phosphor-icons/react";
import { parseGithubUrl } from "@posthog/git/utils";
import type { WorkspaceMode } from "@posthog/shared";
import { formatRelativeTimeShort } from "@posthog/shared";
import type { TaskRunStatus } from "@posthog/shared/domain-types";
import { navigateToPullRequestView } from "@posthog/ui/router/navigationBridge";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { DotsCircleSpinner } from "../../../../primitives/DotsCircleSpinner";
import { NestedButton } from "../../../../primitives/NestedButton";
import { Tooltip } from "../../../../primitives/Tooltip";
import type { SidebarPrState } from "../../useTaskPrStatus";
import { SidebarItem } from "../SidebarItem";
import { ICON_SIZE, TaskIcon } from "./TaskIcon";

function PrBadge({ url, number }: { url: string; number: number }) {
  return (
    <Tooltip content="Open pull request" side="top">
      <NestedButton
        aria-label={`Open pull request #${number}`}
        className="flex h-4 shrink-0 cursor-pointer items-center gap-0.5 rounded bg-gray-3 px-1 text-[11px] text-gray-11 transition-colors hover:bg-gray-4 hover:text-gray-12"
        onActivate={() => {
          navigateToPullRequestView(url);
        }}
      >
        <GitPullRequest size={10} weight="bold" />
        {`#${number}`}
      </NestedButton>
    </Tooltip>
  );
}

interface TaskItemProps {
  depth?: number;
  taskId: string;
  label: string;
  isActive: boolean;
  isSelected?: boolean;
  /** Archive request in flight: show a spinner and suppress hover actions. */
  isArchiving?: boolean;
  hideHoverActions?: boolean;
  workspaceMode?: WorkspaceMode;
  isGenerating?: boolean;
  isUnread?: boolean;
  isPinned?: boolean;
  isSuspended?: boolean;
  needsPermission?: boolean;
  taskRunStatus?: TaskRunStatus;
  originProduct?: string;
  slackThreadUrl?: string;
  prState?: SidebarPrState;
  hasDiff?: boolean;
  prUrl?: string | null;
  timestamp?: number;
  isEditing?: boolean;
  onClick: (e: React.MouseEvent) => void;
  onDoubleClick?: () => void;
  onContextMenu: (e: React.MouseEvent) => void;
  onArchive?: () => void;
  onTogglePin?: () => void;
  onEditSubmit?: (newTitle: string) => void;
  onEditCancel?: () => void;
}

interface TaskHoverToolbarProps {
  isPinned: boolean;
  onTogglePin?: () => void;
  onArchive?: () => void;
}

function TaskHoverToolbar({
  isPinned,
  onTogglePin,
  onArchive,
}: TaskHoverToolbarProps) {
  return (
    <span className="hidden shrink-0 items-center gap-0.5 group-hover:flex">
      {onTogglePin && (
        <Tooltip content={isPinned ? "Unpin task" : "Pin task"} side="top">
          <NestedButton
            aria-label={isPinned ? "Unpin task" : "Pin task"}
            className="flex h-5 w-5 cursor-pointer items-center justify-center rounded text-gray-10 transition-colors hover:bg-gray-4 hover:text-gray-12"
            onActivate={onTogglePin}
          >
            <PushPin size={12} weight={isPinned ? "fill" : "regular"} />
          </NestedButton>
        </Tooltip>
      )}
      {onArchive && (
        <Tooltip content="Archive task" side="top">
          <NestedButton
            aria-label="Archive task"
            className="flex h-5 w-5 cursor-pointer items-center justify-center rounded text-gray-10 transition-colors hover:bg-gray-4 hover:text-gray-12"
            onActivate={onArchive}
          >
            <Archive size={12} />
          </NestedButton>
        </Tooltip>
      )}
    </span>
  );
}

const INDENT_SIZE = 8;

export function TaskItem({
  depth = 0,
  taskId,
  label,
  isActive,
  isSelected = false,
  isArchiving = false,
  hideHoverActions = false,
  workspaceMode,
  isSuspended = false,
  isGenerating,
  isUnread,
  isPinned = false,
  needsPermission = false,
  taskRunStatus,
  originProduct,
  slackThreadUrl,
  prState,
  hasDiff,
  prUrl,
  timestamp,
  isEditing = false,
  onClick,
  onDoubleClick,
  onContextMenu,
  onArchive,
  onTogglePin,
  onEditSubmit,
  onEditCancel,
}: TaskItemProps) {
  const icon = isArchiving ? (
    <DotsCircleSpinner size={ICON_SIZE} className="text-gray-10" />
  ) : (
    <TaskIcon
      workspaceMode={workspaceMode}
      isGenerating={isGenerating}
      isUnread={isUnread}
      isPinned={isPinned}
      isSuspended={isSuspended}
      needsPermission={needsPermission}
      taskRunStatus={taskRunStatus}
      originProduct={originProduct}
      slackThreadUrl={slackThreadUrl}
      prState={prState}
      hasDiff={hasDiff}
    />
  );

  const prRef = useMemo(() => (prUrl ? parseGithubUrl(prUrl) : null), [prUrl]);
  const prBadge =
    prUrl && prRef?.kind === "pr" ? (
      <PrBadge url={prUrl} number={prRef.number} />
    ) : null;

  // The PR badge takes the timestamp's slot, so hide the timestamp when shown.
  const timestampNode =
    timestamp && !prBadge ? (
      <span className="shrink-0 text-[11px] text-gray-11 group-hover:hidden">
        {formatRelativeTimeShort(timestamp)}
      </span>
    ) : null;

  const toolbar =
    !isArchiving && !hideHoverActions && (onArchive || onTogglePin) ? (
      <TaskHoverToolbar
        isPinned={isPinned}
        onTogglePin={onTogglePin}
        onArchive={onArchive}
      />
    ) : null;

  const endContent =
    prBadge || timestampNode || toolbar ? (
      <>
        {prBadge}
        {timestampNode}
        {toolbar}
      </>
    ) : null;

  const handleDragStart = useCallback(
    (e: React.DragEvent) => {
      e.dataTransfer.setData("text/x-task-id", taskId);
      e.dataTransfer.effectAllowed = "copy";
    },
    [taskId],
  );

  if (isEditing) {
    return (
      <InlineEditInput
        depth={depth}
        icon={icon}
        label={label}
        isActive={isActive}
        onSubmit={(newTitle) => onEditSubmit?.(newTitle)}
        onCancel={() => onEditCancel?.()}
      />
    );
  }

  return (
    <SidebarItem
      depth={depth}
      icon={icon}
      label={label}
      isActive={isActive}
      isSelected={isSelected}
      isDimmed={isArchiving}
      draggable={!isArchiving}
      onDragStart={handleDragStart}
      onClick={onClick}
      onDoubleClick={onDoubleClick}
      onContextMenu={onContextMenu}
      endContent={endContent}
    />
  );
}

function InlineEditInput({
  depth,
  icon,
  label,
  isActive,
  onSubmit,
  onCancel,
}: {
  depth: number;
  icon: React.ReactNode;
  label: string;
  isActive: boolean;
  onSubmit: (newTitle: string) => void;
  onCancel: () => void;
}) {
  const [editValue, setEditValue] = useState(label);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const input = inputRef.current;
    if (input) {
      input.focus();
      input.select();
    }
  }, []);

  const handleSubmit = () => {
    const trimmed = editValue.trim();
    if (trimmed && trimmed !== label) {
      onSubmit(trimmed);
    } else {
      onCancel();
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter") {
      e.preventDefault();
      handleSubmit();
    } else if (e.key === "Escape") {
      e.preventDefault();
      onCancel();
    }
  };

  return (
    <div
      className={`flex w-full items-start gap-[4px] px-2 py-1.5 text-[13px]${isActive ? "bg-accent-4 text-gray-12" : ""}`}
      style={{
        paddingLeft: `${depth * INDENT_SIZE + 8 + (depth > 0 ? 4 : 0)}px`,
      }}
    >
      {icon && (
        <span
          className={`flex h-[18px] w-[18px] shrink-0 items-center justify-center ${isActive ? "text-gray-11" : "text-gray-10"}`}
        >
          {icon}
        </span>
      )}
      <span className="flex min-w-0 flex-1 flex-col overflow-hidden">
        <span className="flex h-[18px] items-center">
          <input
            ref={inputRef}
            type="text"
            value={editValue}
            onChange={(e) => setEditValue(e.target.value)}
            onKeyDown={handleKeyDown}
            onBlur={handleSubmit}
            className="h-[18px] min-w-0 flex-1 rounded-sm border border-accent-8 bg-gray-2 px-1 text-[13px] text-gray-12 outline-none"
          />
        </span>
      </span>
    </div>
  );
}
