import { PointerSensor } from "@dnd-kit/dom";
import type { DragDropEvents } from "@dnd-kit/react";
import { DragDropProvider } from "@dnd-kit/react";
import { GitBranch, Wrench } from "@phosphor-icons/react";
import {
  findGroupFolder,
  groupTasksByRelativeDate,
} from "@posthog/core/sidebar/groupTasks";
import { mostRecentRunEnvironment } from "@posthog/core/sidebar/runEnvironment";
import type {
  TaskData,
  TaskGroup,
} from "@posthog/core/sidebar/sidebarData.types";
import { MenuLabel } from "@posthog/quill";
import { builderHog } from "@posthog/ui/assets/hedgehogs";
import { useFolders } from "@posthog/ui/features/folders/useFolders";
import { useSettingsStore } from "@posthog/ui/features/settings/settingsStore";
import { useArchivingTasksStore } from "@posthog/ui/features/sidebar/archivingTasksStore";
import { DraggableFolder } from "@posthog/ui/features/sidebar/components/DraggableFolder";
import { GroupWorktreesSection } from "@posthog/ui/features/sidebar/components/GroupWorktreesSection";
import { TaskItem } from "@posthog/ui/features/sidebar/components/items/TaskItem";
import { SidebarSection } from "@posthog/ui/features/sidebar/components/SidebarSection";
import { useSidebarStore } from "@posthog/ui/features/sidebar/sidebarStore";
import { useTaskPrStatus } from "@posthog/ui/features/sidebar/useTaskPrStatus";
import { useWorkspace } from "@posthog/ui/features/workspace/useWorkspace";
import { useAppView } from "@posthog/ui/router/useAppView";
import { openTaskInput } from "@posthog/ui/router/useOpenTask";
import { Flex, Text } from "@radix-ui/themes";
import { motion } from "framer-motion";
import { Fragment, useCallback, useEffect, useMemo } from "react";

interface TaskListViewProps {
  pinnedTasks: TaskData[];
  flatTasks: TaskData[];
  groupedTasks: TaskGroup[];
  activeTaskId: string | null;
  editingTaskId: string | null;
  selectedTaskIds: string[];
  onTaskClick: (taskId: string, e: React.MouseEvent) => void;
  onTaskDoubleClick: (taskId: string) => void;
  onTaskContextMenu: (
    taskId: string,
    e: React.MouseEvent,
    isPinned: boolean,
  ) => void;
  onTaskArchive: (taskId: string) => void;
  onTaskTogglePin: (taskId: string) => void;
  onTaskEditSubmit: (
    taskId: string,
    currentTitle: string,
    newTitle: string,
  ) => void;
  onTaskEditCancel: () => void;
  onGroupContextMenu?: (groupId: string, e: React.MouseEvent) => void;
  hasMore: boolean;
}

function SectionLabel({ label }: { label: string }) {
  return <MenuLabel className="flex items-center py-0">{label}</MenuLabel>;
}

function TaskRow({
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
  timestamp,
  depth = 0,
}: {
  task: TaskData;
  isActive: boolean;
  isSelected: boolean;
  hideHoverActions: boolean;
  isEditing: boolean;
  onClick: (e: React.MouseEvent) => void;
  onDoubleClick: () => void;
  onContextMenu: (e: React.MouseEvent, isPinned: boolean) => void;
  onArchive: () => void;
  onTogglePin: () => void;
  onEditSubmit: (newTitle: string) => void;
  onEditCancel: () => void;
  timestamp: number;
  depth?: number;
}) {
  const workspace = useWorkspace(task.id);
  const effectiveMode =
    workspace?.mode ??
    (task.taskRunEnvironment === "cloud" ? "cloud" : undefined);

  const { prState, hasDiff } = useTaskPrStatus(task);
  const isArchiving = useArchivingTasksStore((s) =>
    s.archivingTaskIds.has(task.id),
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
      originProduct={task.originProduct}
      slackThreadUrl={task.slackThreadUrl}
      prState={prState}
      hasDiff={hasDiff}
      prUrl={task.cloudPrUrl}
      timestamp={timestamp}
      onClick={onClick}
      onDoubleClick={onDoubleClick}
      onContextMenu={(e) => onContextMenu(e, task.isPinned)}
      onArchive={onArchive}
      onTogglePin={onTogglePin}
      onEditSubmit={onEditSubmit}
      onEditCancel={onEditCancel}
    />
  );
}

export function TaskListView({
  pinnedTasks,
  flatTasks,
  groupedTasks,
  activeTaskId,
  editingTaskId,
  selectedTaskIds,
  onTaskClick,
  onTaskDoubleClick,
  onTaskContextMenu,
  onTaskArchive,
  onTaskTogglePin,
  onTaskEditSubmit,
  onTaskEditCancel,
  onGroupContextMenu,
  hasMore,
}: TaskListViewProps) {
  const selectedIdSet = useMemo(
    () => new Set(selectedTaskIds),
    [selectedTaskIds],
  );
  const hasMultiSelection = selectedTaskIds.length > 1;
  const organizeMode = useSidebarStore((state) => state.organizeMode);
  const sortMode = useSidebarStore((state) => state.sortMode);
  const collapsedSections = useSidebarStore((state) => state.collapsedSections);
  const toggleSection = useSidebarStore((state) => state.toggleSection);
  const loadMoreHistory = useSidebarStore((state) => state.loadMoreHistory);
  const resetHistoryVisibleCount = useSidebarStore(
    (state) => state.resetHistoryVisibleCount,
  );
  const { folders } = useFolders();
  const showSidebarWorktrees = useSettingsStore(
    (state) => state.showSidebarWorktrees,
  );
  const view = useAppView();
  const isOnTaskInput =
    view.type === "task-input" || view.type === "task-pending";

  // biome-ignore lint/correctness/useExhaustiveDependencies: reset pagination when filters change
  useEffect(() => {
    resetHistoryVisibleCount();
  }, [organizeMode, sortMode, resetHistoryVisibleCount]);

  const handleDragOver: DragDropEvents["dragover"] = useCallback((event) => {
    const sourceId = event.operation.source?.id;
    const targetId = event.operation.target?.id;
    if (!sourceId || !targetId || sourceId === targetId) return;

    const currentOrder = useSidebarStore.getState().folderOrder;
    const sourceIndex = currentOrder.indexOf(String(sourceId));
    const targetIndex = currentOrder.indexOf(String(targetId));
    if (sourceIndex === -1 || targetIndex === -1) return;
    if (sourceIndex === targetIndex) return;

    useSidebarStore.getState().reorderFolders(sourceIndex, targetIndex);
  }, []);

  const timestampKey: "lastActivityAt" | "createdAt" =
    sortMode === "updated" ? "lastActivityAt" : "createdAt";

  const dateGroupedTasks = useMemo(
    () => groupTasksByRelativeDate(flatTasks, timestampKey),
    [flatTasks, timestampKey],
  );

  return (
    <Flex direction="column">
      {pinnedTasks.length > 0 && (
        <>
          <SectionLabel label="Pinned" />
          {pinnedTasks.map((task) => (
            <TaskRow
              key={task.id}
              task={task}
              isActive={activeTaskId === task.id}
              isSelected={selectedIdSet.has(task.id)}
              hideHoverActions={hasMultiSelection}
              isEditing={editingTaskId === task.id}
              onClick={(e) => onTaskClick(task.id, e)}
              onDoubleClick={() => onTaskDoubleClick(task.id)}
              onContextMenu={(e, isPinned) =>
                onTaskContextMenu(task.id, e, isPinned)
              }
              onArchive={() => onTaskArchive(task.id)}
              onTogglePin={() => onTaskTogglePin(task.id)}
              onEditSubmit={(newTitle) =>
                onTaskEditSubmit(task.id, task.title, newTitle)
              }
              onEditCancel={onTaskEditCancel}
              timestamp={task[timestampKey]}
            />
          ))}
        </>
      )}

      {pinnedTasks.length === 0 &&
      flatTasks.length === 0 &&
      groupedTasks.length === 0 ? (
        <div className="flex flex-col items-center gap-1 px-4 pt-6 pb-4 text-center">
          <motion.img
            src={builderHog}
            alt=""
            className="pointer-events-none w-[72px]"
            initial={{ opacity: 0, y: 8 }}
            animate={{
              opacity: 1,
              y: [0, -4, 0],
            }}
            transition={{
              opacity: { duration: 0.4 },
              y: {
                duration: 3,
                repeat: Infinity,
                ease: "easeInOut",
                delay: 0.4,
              },
            }}
          />
          <Text className="text-[13px] text-gray-10">No tasks yet</Text>
          {!isOnTaskInput && (
            <motion.button
              type="button"
              className="mt-1 rounded-md bg-gray-3 px-3 py-1.5 text-[13px] text-gray-12"
              onClick={() => openTaskInput()}
              whileHover={{ scale: 1.05, backgroundColor: "var(--gray-4)" }}
              whileTap={{ scale: 0.97 }}
            >
              Start building
            </motion.button>
          )}
        </div>
      ) : organizeMode === "by-project" ? (
        <DragDropProvider
          onDragOver={handleDragOver}
          sensors={[
            {
              plugin: PointerSensor,
              options: {
                activationConstraints: {
                  distance: { value: 5 },
                },
              },
            },
          ]}
        >
          <Flex direction="column">
            {groupedTasks.map((group, index) => {
              const isExpanded = !collapsedSections.has(group.id);
              const folder = findGroupFolder(folders, group.id);
              const groupFolderId =
                folder?.id ?? group.tasks.find((t) => t.folderId)?.folderId;
              return (
                <DraggableFolder key={group.id} id={group.id} index={index}>
                  <SidebarSection
                    id={group.id}
                    label={folder?.name ?? group.name}
                    icon={
                      group.id === "custom-images" ? (
                        <Wrench size={14} className="text-gray-10" />
                      ) : (
                        <GitBranch size={14} className="text-gray-10" />
                      )
                    }
                    isExpanded={isExpanded}
                    onToggle={() => toggleSection(group.id)}
                    addSpacingBefore={false}
                    tooltipContent={folder?.path ?? group.id}
                    onNewTask={() => {
                      if (groupFolderId) {
                        openTaskInput({
                          folderId: groupFolderId,
                          folderRunEnvironment: mostRecentRunEnvironment(
                            group.tasks,
                          ),
                        });
                      } else {
                        openTaskInput();
                      }
                    }}
                    newTaskTooltip={`Start new task in ${folder?.name ?? group.name}`}
                    onContextMenu={
                      onGroupContextMenu
                        ? (e) => onGroupContextMenu(group.id, e)
                        : undefined
                    }
                  >
                    {group.tasks.length === 0 ? (
                      <p className="px-4 py-2 text-[12px] text-gray-9">
                        No tasks yet
                      </p>
                    ) : (
                      group.tasks.map((task) => (
                        <TaskRow
                          key={task.id}
                          task={task}
                          isActive={activeTaskId === task.id}
                          isSelected={selectedIdSet.has(task.id)}
                          hideHoverActions={hasMultiSelection}
                          isEditing={editingTaskId === task.id}
                          onClick={(e) => onTaskClick(task.id, e)}
                          onDoubleClick={() => onTaskDoubleClick(task.id)}
                          onContextMenu={(e, isPinned) =>
                            onTaskContextMenu(task.id, e, isPinned)
                          }
                          onArchive={() => onTaskArchive(task.id)}
                          onTogglePin={() => onTaskTogglePin(task.id)}
                          onEditSubmit={(newTitle) =>
                            onTaskEditSubmit(task.id, task.title, newTitle)
                          }
                          onEditCancel={onTaskEditCancel}
                          timestamp={task[timestampKey]}
                          depth={1}
                        />
                      ))
                    )}
                    {folder && showSidebarWorktrees && (
                      <GroupWorktreesSection
                        groupId={group.id}
                        mainRepoPath={folder.mainRepoPath ?? folder.path}
                      />
                    )}
                  </SidebarSection>
                </DraggableFolder>
              );
            })}
          </Flex>
        </DragDropProvider>
      ) : (
        <Flex direction="column" gap="1px">
          {dateGroupedTasks.map((group, groupIndex) => (
            <Fragment key={`${group.label ?? "today"}-${groupIndex}`}>
              {group.label && <SectionLabel label={group.label} />}
              {group.tasks.map((task) => (
                <TaskRow
                  key={task.id}
                  task={task}
                  isActive={activeTaskId === task.id}
                  isSelected={selectedIdSet.has(task.id)}
                  hideHoverActions={hasMultiSelection}
                  isEditing={editingTaskId === task.id}
                  onClick={(e) => onTaskClick(task.id, e)}
                  onDoubleClick={() => onTaskDoubleClick(task.id)}
                  onContextMenu={(e, isPinned) =>
                    onTaskContextMenu(task.id, e, isPinned)
                  }
                  onArchive={() => onTaskArchive(task.id)}
                  onTogglePin={() => onTaskTogglePin(task.id)}
                  onEditSubmit={(newTitle) =>
                    onTaskEditSubmit(task.id, task.title, newTitle)
                  }
                  onEditCancel={onTaskEditCancel}
                  timestamp={task[timestampKey]}
                />
              ))}
            </Fragment>
          ))}
        </Flex>
      )}

      {/* Rendered for both organize modes: "by-project" caps each group and
          "chronological" caps the flat list, so either can have more to load. */}
      {hasMore && (
        <div className="px-2 py-2">
          <button
            type="button"
            className="w-full rounded-md px-2 py-1 text-left text-[13px] text-gray-11 transition-colors hover:bg-gray-3"
            onClick={loadMoreHistory}
          >
            Show more
          </button>
        </div>
      )}
    </Flex>
  );
}
