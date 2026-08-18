import type { TaskData } from "@posthog/core/sidebar/sidebarData.types";
import { useArchivingTasksStore } from "@posthog/ui/features/sidebar/archivingTasksStore";
import { TaskItem } from "@posthog/ui/features/sidebar/components/items/TaskItem";
import { useTaskPrStatus } from "@posthog/ui/features/sidebar/useTaskPrStatus";
import { useWorkspace } from "@posthog/ui/features/workspace/useWorkspace";

interface TaskRowProps {
  task: TaskData;
  isActive: boolean;
  isSelected: boolean;
  hideHoverActions: boolean;
  isEditing: boolean;
  onClick: (event: React.MouseEvent) => void;
  onDoubleClick: () => void;
  onContextMenu: (event: React.MouseEvent, isPinned: boolean) => void;
  onArchive: () => void;
  onTogglePin: () => void;
  onEditSubmit: (newTitle: string) => void;
  onEditCancel: () => void;
  onDragStart?: (event: React.DragEvent) => void;
  onDragEnd?: (event: React.DragEvent) => void;
  timestamp: number;
  depth?: number;
}

export function TaskRow({
  task,
  isActive,
  isSelected,
  hideHoverActions,
  isEditing,
  onClick,
  onDoubleClick,
  onContextMenu,
  onArchive,
  onTogglePin,
  onEditSubmit,
  onEditCancel,
  onDragStart,
  onDragEnd,
  timestamp,
  depth = 0,
}: TaskRowProps) {
  const workspace = useWorkspace(task.id);
  const effectiveMode =
    workspace?.mode ??
    (task.taskRunEnvironment === "cloud" ? "cloud" : undefined);
  const { prState, hasDiff } = useTaskPrStatus(task);
  const isArchiving = useArchivingTasksStore((state) =>
    state.archivingTaskIds.has(task.id),
  );

  return (
    <TaskItem
      depth={depth}
      taskId={task.id}
      label={task.title}
      isActive={isActive}
      isSelected={isSelected}
      isArchiving={isArchiving}
      hideHoverActions={hideHoverActions}
      isEditing={isEditing}
      workspaceMode={effectiveMode}
      isSuspended={task.isSuspended}
      isGenerating={task.isGenerating}
      isUnread={task.isUnread}
      isPinned={task.isPinned}
      needsPermission={task.needsPermission}
      taskRunStatus={task.taskRunStatus}
      runMode={task.runMode}
      originProduct={task.originProduct}
      slackThreadUrl={task.slackThreadUrl}
      prState={prState}
      hasDiff={hasDiff}
      prUrl={task.cloudPrUrl}
      timestamp={timestamp}
      onClick={onClick}
      onDoubleClick={onDoubleClick}
      onContextMenu={(event) => onContextMenu(event, task.isPinned)}
      onDragStart={onDragStart}
      onDragEnd={onDragEnd}
      onArchive={onArchive}
      onTogglePin={onTogglePin}
      onEditSubmit={onEditSubmit}
      onEditCancel={onEditCancel}
    />
  );
}
