import { PointerSensor } from "@dnd-kit/dom";
import type { DragDropEvents } from "@dnd-kit/react";
import { DragDropProvider } from "@dnd-kit/react";
import { GitBranch, Trash, Wrench } from "@phosphor-icons/react";
import {
  findGroupFolder,
  groupTasksByRelativeDate,
} from "@posthog/core/sidebar/groupTasks";
import { mostRecentRunEnvironment } from "@posthog/core/sidebar/runEnvironment";
import type {
  TaskData,
  TaskGroup,
} from "@posthog/core/sidebar/sidebarData.types";
import { cn, MenuLabel, Text } from "@posthog/quill";
import { builderHog } from "@posthog/ui/assets/hedgehogs";
import { useFolders } from "@posthog/ui/features/folders/useFolders";
import { useSettingsStore } from "@posthog/ui/features/settings/settingsStore";
import { DragBatchLabel } from "@posthog/ui/features/sidebar/components/DragBatchLabel";
import { DraggableFolder } from "@posthog/ui/features/sidebar/components/DraggableFolder";
import { GroupWorktreesSection } from "@posthog/ui/features/sidebar/components/GroupWorktreesSection";
import { taskMetadata } from "@posthog/ui/features/sidebar/components/ListItemMetadata";
import { SidebarSection } from "@posthog/ui/features/sidebar/components/SidebarSection";
import { TaskRow } from "@posthog/ui/features/sidebar/components/TaskRow";
import { useSidebarStore } from "@posthog/ui/features/sidebar/sidebarStore";
import {
  dragSiblingCandidates,
  taskDragSiblings,
} from "@posthog/ui/features/sidebar/taskDrag";
import {
  getPinnedInsertionIndex,
  type TaskTimestampKey,
} from "@posthog/ui/features/sidebar/taskListDragAndDrop";
import { usePinDrag } from "@posthog/ui/features/sidebar/usePinDrag";
import { useAppView } from "@posthog/ui/router/useAppView";
import { openTaskInput } from "@posthog/ui/router/useOpenTask";
import {
  AnimatePresence,
  LayoutGroup,
  motion,
  useReducedMotion,
} from "framer-motion";
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
  /** Pins or unpins a whole batch, which a drag over the pinned run applies. */
  onTasksSetPinned: (taskIds: string[], pinned: boolean) => void;
  onTaskEditSubmit: (
    taskId: string,
    currentTitle: string,
    newTitle: string,
  ) => void;
  onTaskEditCancel: () => void;
  onGroupContextMenu?: (groupId: string, e: React.MouseEvent) => void;
  creatorNameByTaskId: ReadonlyMap<string, string>;
  hasMore: boolean;
}

function SectionLabel({ label }: { label: string }) {
  return <MenuLabel className="flex items-center py-0">{label}</MenuLabel>;
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
  onTasksSetPinned,
  onTaskEditSubmit,
  onTaskEditCancel,
  onGroupContextMenu,
  creatorNameByTaskId,
  hasMore,
}: TaskListViewProps) {
  const selectedIdSet = useMemo(
    () => new Set(selectedTaskIds),
    [selectedTaskIds],
  );
  const hasMultiSelection = selectedTaskIds.length > 1;
  const organizeMode = useSidebarStore((state) => state.organizeMode);
  const sortMode = useSidebarStore((state) => state.sortMode);
  const listItemMetadataFields = useSidebarStore(
    (state) => state.listItemMetadataFields,
  );
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
  const prefersReducedMotion = useReducedMotion();
  // A drag that starts on a selected row carries the whole selection, so a pin
  // or an unpin applies to every row the user picked, not just the grabbed one.
  const allTasks = useMemo(
    () =>
      dragSiblingCandidates(organizeMode, {
        pinnedTasks,
        flatTasks,
        groupedTasks,
      }),
    [organizeMode, pinnedTasks, flatTasks, groupedTasks],
  );
  const dragSiblingsFor = useCallback(
    (task: TaskData) => taskDragSiblings(task.id, allTasks, (t) => t.id),
    [allTasks],
  );
  const pinDrag = usePinDrag<TaskData>({
    isPinned: (task) => task.isPinned,
    setPinned: (tasks, pinned) =>
      onTasksSetPinned(
        tasks.map((task) => task.id),
        pinned,
      ),
    getDragSiblings: dragSiblingsFor,
  });
  const dragState = pinDrag.drag;

  // biome-ignore lint/correctness/useExhaustiveDependencies: reset pagination when filters change
  useEffect(() => {
    resetHistoryVisibleCount();
  }, [organizeMode, sortMode, resetHistoryVisibleCount]);

  const timestampKey: TaskTimestampKey =
    sortMode === "updated" ? "lastActivityAt" : "createdAt";

  const dateGroupedTasks = useMemo(
    () => groupTasksByRelativeDate(flatTasks, timestampKey),
    [flatTasks, timestampKey],
  );

  const handleFolderDragOver: DragDropEvents["dragover"] = useCallback(
    (event) => {
      const sourceId = event.operation.source?.id;
      const targetId = event.operation.target?.id;
      if (!sourceId || !targetId || sourceId === targetId) return;

      const currentOrder = useSidebarStore.getState().folderOrder;
      const sourceIndex = currentOrder.indexOf(String(sourceId));
      const targetIndex = currentOrder.indexOf(String(targetId));
      if (sourceIndex === -1 || targetIndex === -1) return;
      if (sourceIndex === targetIndex) return;

      useSidebarStore.getState().reorderFolders(sourceIndex, targetIndex);
    },
    [],
  );

  const rowTransition = prefersReducedMotion
    ? { duration: 0 }
    : {
        layout: { type: "spring" as const, stiffness: 520, damping: 42 },
        height: { duration: 0.16, ease: "easeOut" as const },
        opacity: { duration: 0.1 },
      };

  const draggedIdSet = useMemo(
    () => new Set(dragState?.items.map((task) => task.id) ?? []),
    [dragState],
  );

  const renderTaskRow = (task: TaskData, depth = 0) => {
    const isDragged = draggedIdSet.has(task.id);
    return (
      <motion.div
        key={task.id}
        layout={prefersReducedMotion ? false : "position"}
        layoutId={`sidebar-task-${task.id}`}
        initial={false}
        animate={
          isDragged
            ? { height: 0, opacity: 0, scale: 0.98 }
            : { height: "auto", opacity: 1, scale: 1 }
        }
        transition={rowTransition}
        className="overflow-hidden"
      >
        <TaskRow
          task={task}
          isActive={activeTaskId === task.id}
          isSelected={selectedIdSet.has(task.id)}
          hideHoverActions={hasMultiSelection}
          isEditing={editingTaskId === task.id}
          onClick={(event) => onTaskClick(task.id, event)}
          onDoubleClick={() => onTaskDoubleClick(task.id)}
          onContextMenu={(event, isPinned) =>
            onTaskContextMenu(task.id, event, isPinned)
          }
          onArchive={() => onTaskArchive(task.id)}
          onTogglePin={() => onTaskTogglePin(task.id)}
          onEditSubmit={(newTitle) =>
            onTaskEditSubmit(task.id, task.title, newTitle)
          }
          onEditCancel={onTaskEditCancel}
          onDragStart={(event) => pinDrag.onItemDragStart(task, event)}
          onDragEnd={pinDrag.onItemDragEnd}
          timestamp={task[timestampKey]}
          subtitle={taskMetadata(
            task,
            creatorNameByTaskId.get(task.id),
            listItemMetadataFields,
          )}
          depth={depth}
        />
      </motion.div>
    );
  };

  const pinnedTasksWithoutSource = pinnedTasks.filter(
    (task) => !draggedIdSet.has(task.id),
  );
  const pinnedInsertionIndex = dragState
    ? getPinnedInsertionIndex(pinnedTasks, dragState.items[0], timestampKey)
    : -1;
  const showPinnedPlaceholder = Boolean(dragState?.overPinned);
  const pinnedPlaceholderBeforeTaskId =
    pinnedTasksWithoutSource[pinnedInsertionIndex]?.id;
  const pinnedPlaceholder = (
    <motion.div
      key="pinned-task-placeholder"
      layout
      initial={{ height: 0, opacity: 0 }}
      animate={{ height: 28, opacity: 1 }}
      exit={{ height: 0, opacity: 0 }}
      transition={
        prefersReducedMotion
          ? { duration: 0 }
          : { type: "spring", stiffness: 520, damping: 42 }
      }
      className="mx-1 rounded-md border border-accent-6 bg-accent-3"
    />
  );
  const showPinnedSection = pinnedTasks.length > 0 || dragState !== null;
  const isUnpinIntent = Boolean(
    dragState?.sourcePinned && !dragState.overPinned,
  );

  return (
    <LayoutGroup id="sidebar-task-list">
      {/* Pin and unpin stay reachable from the row's hover actions and its
          context menu, so the drag adds no keyboard-only path. */}
      {/* biome-ignore lint/a11y/noStaticElementInteractions: drag-and-drop container */}
      <div
        className="flex min-h-full flex-1 flex-col"
        onDragOver={pinDrag.listProps.onDragOver}
        onDrop={pinDrag.listProps.onDrop}
      >
        {showPinnedSection ? (
          <motion.div
            ref={pinDrag.pinnedZoneRef}
            layout
            className={cn(
              "rounded-md py-0.5 transition-colors",
              dragState && "min-h-10",
              dragState?.overPinned &&
                !dragState.sourcePinned &&
                "bg-accent-2 ring-1 ring-accent-6",
            )}
          >
            <SectionLabel label="Pinned" />
            <AnimatePresence initial={false}>
              {pinnedTasks.map((task) => (
                <Fragment key={task.id}>
                  {showPinnedPlaceholder &&
                  task.id === pinnedPlaceholderBeforeTaskId
                    ? pinnedPlaceholder
                    : null}
                  {renderTaskRow(task)}
                </Fragment>
              ))}
              {showPinnedPlaceholder && !pinnedPlaceholderBeforeTaskId
                ? pinnedPlaceholder
                : null}
            </AnimatePresence>
          </motion.div>
        ) : null}

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
                y: prefersReducedMotion ? 0 : [0, -4, 0],
              }}
              transition={{
                opacity: { duration: prefersReducedMotion ? 0 : 0.4 },
                y: {
                  duration: prefersReducedMotion ? 0 : 3,
                  repeat: prefersReducedMotion ? 0 : Infinity,
                  ease: "easeInOut",
                  delay: prefersReducedMotion ? 0 : 0.4,
                },
              }}
            />
            <Text size="sm" variant="muted">
              No tasks yet
            </Text>
            {!isOnTaskInput && (
              <motion.button
                type="button"
                className="mt-1 rounded-md bg-gray-3 px-3 py-1.5 text-[13px] text-gray-12"
                onClick={() => openTaskInput()}
                whileHover={
                  prefersReducedMotion
                    ? undefined
                    : { scale: 1.05, backgroundColor: "var(--gray-4)" }
                }
                whileTap={prefersReducedMotion ? undefined : { scale: 0.97 }}
              >
                Start building
              </motion.button>
            )}
          </div>
        ) : organizeMode === "by-project" ? (
          <DragDropProvider
            onDragOver={handleFolderDragOver}
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
            <div className="flex flex-col">
              {groupedTasks.map((group, index) => {
                const isExpanded = !collapsedSections.has(group.id);
                const folder = findGroupFolder(folders, group.id);
                const groupFolderId =
                  folder?.id ??
                  group.tasks.find((task) => task.folderId)?.folderId;
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
                        openTaskInput({
                          folderId: groupFolderId,
                          // Cloud-only groups have no registered folder, and the
                          // group id is the repo slug. Without it the new-task
                          // screen keeps whichever repo was last used.
                          folderRepository: group.id,
                          folderRunEnvironment: mostRecentRunEnvironment(
                            group.tasks,
                          ),
                        });
                      }}
                      newTaskTooltip={`Start new task in ${folder?.name ?? group.name}`}
                      onContextMenu={
                        onGroupContextMenu
                          ? (event) => onGroupContextMenu(group.id, event)
                          : undefined
                      }
                    >
                      {group.tasks.length === 0 ? (
                        <p className="px-4 py-2 text-[12px] text-gray-9">
                          No tasks yet
                        </p>
                      ) : (
                        group.tasks.map((task) => renderTaskRow(task, 1))
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
            </div>
          </DragDropProvider>
        ) : (
          <div className="flex flex-col gap-px">
            {dateGroupedTasks.map((group, groupIndex) => (
              <Fragment key={`${group.label ?? "today"}-${groupIndex}`}>
                {group.label && <SectionLabel label={group.label} />}
                {group.tasks.map((task) => renderTaskRow(task))}
              </Fragment>
            ))}
          </div>
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

        {dragState ? (
          <motion.div
            style={{
              x: pinDrag.previewX,
              y: pinDrag.previewY,
              width: dragState.previewWidth,
            }}
            className="pointer-events-none fixed top-0 left-0 z-50"
          >
            <motion.div
              initial={false}
              animate={
                isUnpinIntent
                  ? { rotate: 1.5, scale: 1.02 }
                  : { rotate: 0, scale: 1 }
              }
              transition={
                prefersReducedMotion
                  ? { duration: 0 }
                  : { type: "spring", stiffness: 500, damping: 34 }
              }
              className={cn(
                "relative overflow-hidden rounded-md border bg-gray-2 shadow-lg",
                isUnpinIntent
                  ? "border-red-7 bg-red-3 [&_button]:bg-red-3 [&_button]:text-red-12 [&_svg]:text-red-11"
                  : "border-gray-6",
              )}
            >
              {dragState.items.length > 1 ? (
                <DragBatchLabel count={dragState.items.length} />
              ) : (
                <TaskRow
                  task={dragState.items[0]}
                  isActive={false}
                  isSelected={false}
                  hideHoverActions
                  isEditing={false}
                  onClick={() => undefined}
                  onDoubleClick={() => undefined}
                  onContextMenu={() => undefined}
                  onArchive={() => undefined}
                  onTogglePin={() => undefined}
                  onEditSubmit={() => undefined}
                  onEditCancel={() => undefined}
                  timestamp={dragState.items[0][timestampKey]}
                  subtitle={taskMetadata(
                    dragState.items[0],
                    creatorNameByTaskId.get(dragState.items[0].id),
                    listItemMetadataFields,
                  )}
                  withPrStatus={false}
                />
              )}
              <AnimatePresence>
                {isUnpinIntent ? (
                  <motion.span
                    initial={{ opacity: 0, scale: 0.7 }}
                    animate={{ opacity: 1, scale: 1 }}
                    exit={{ opacity: 0, scale: 0.7 }}
                    transition={
                      prefersReducedMotion
                        ? { duration: 0 }
                        : { type: "spring", stiffness: 560, damping: 32 }
                    }
                    className="-translate-y-1/2 absolute top-1/2 right-2 flex size-5 items-center justify-center rounded-full bg-red-9 text-white shadow-sm"
                  >
                    <Trash size={12} weight="bold" />
                  </motion.span>
                ) : null}
              </AnimatePresence>
            </motion.div>
          </motion.div>
        ) : null}
      </div>
    </LayoutGroup>
  );
}
