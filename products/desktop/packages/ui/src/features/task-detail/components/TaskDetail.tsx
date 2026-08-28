import type { Task } from "@posthog/shared/domain-types";
import { Box, Flex, Text, Tooltip } from "@radix-ui/themes";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useHotkeys, useHotkeysContext } from "react-hotkeys-hook";
import { useBlurOnEscape } from "../../../hooks/useBlurOnEscape";
import { useSetHeaderContent } from "../../../hooks/useSetHeaderContent";
import { logger } from "../../../shell/logger";
import { useTaskArchive } from "../../archive/useTaskArchive";
import { ChannelBreadcrumb } from "../../canvas/components/ChannelBreadcrumb";
import { CopyThreadLinkButton } from "../../canvas/components/CopyThreadLinkButton";
import { useMarkTaskActivityRead } from "../../canvas/hooks/useMarkTaskActivityRead";
import {
  LazyCloudReviewPage as CloudReviewPage,
  LazyReviewPage as ReviewPage,
} from "../../code-review/components/LazyReviewPages";
import { useReviewNavigationStore } from "../../code-review/reviewNavigationStore";
import { useFileSearchStore } from "../../command/fileSearchStore";
import { SHORTCUTS } from "../../command/keyboard-shortcuts";
import { useRepoFileWatcher } from "../../file-watcher/useRepoFileWatcher";
import { clearGitReviewQueries } from "../../git-interaction/gitCacheKeys";
import { useRightPanelStore } from "../../navigation/rightPanelStore";
import { useReviewInRightPanel } from "../../navigation/useReviewInRightPanel";
import { PanelLayout } from "../../panels/components/PanelLayout";
import { MIN_CHAT_WIDTH } from "../../sessions/constants";
import { useCwd } from "../../sidebar/useCwd";
import { useRenameTask } from "../../tasks/useTaskMutations";
import { useWorkspace } from "../../workspace/useWorkspace";
import { useWorkspaceEvents } from "../../workspace/useWorkspaceEvents";
import { HeaderTitleEditor } from "../HeaderTitleEditor";
import { useTaskData } from "../hooks/useTaskData";
import { CustomImageBadge } from "./CustomImageBadge";
import { TaskHeaderMark, TaskHeaderMarks } from "./TaskHeaderStatus";

const MIN_REVIEW_WIDTH = 300;
const log = logger.scope("task-detail");

interface TaskDetailProps {
  task: Task;
  /**
   * When the task is opened inside a channel, the channel name to prefix the
   * header title with as a "# channel / title" breadcrumb. Omitted for the
   * plain Code task view.
   */
  channelName?: string;
  /** The channel's id, so the breadcrumb's "# channel" links to its home. */
  channelId?: string;
}

export function TaskDetail({
  task: initialTask,
  channelName,
  channelId,
}: TaskDetailProps) {
  const taskId = initialTask.id;
  const { task } = useTaskData({ taskId, initialTask });

  const effectiveRepoPath = useCwd(taskId);

  const openFilePicker = useFileSearchStore((state) => state.openPicker);

  const { enableScope, disableScope } = useHotkeysContext();
  const { requestArchive, dialog: archiveDialog } = useTaskArchive(task, {
    navigateUnscoped: !channelId,
  });

  useHotkeys(
    SHORTCUTS.ARCHIVE_TASK,
    (event) => {
      event.preventDefault();
      requestArchive();
    },
    {
      scopes: ["taskDetail"],
      enableOnContentEditable: true,
      enableOnFormTags: true,
    },
    [requestArchive],
  );

  useEffect(() => {
    enableScope("taskDetail");
    return () => {
      disableScope("taskDetail");
    };
  }, [enableScope, disableScope]);

  // Mounting TaskDetail means the task was actually rendered in front of the
  // user — that, not any API fetch of the task, is what clears the unread
  // activity flag ("the agent is waiting for your reply"). Now-based rather
  // than row-versioned since everything up to mount has been seen; a waiting
  // flag landing after mount re-flags unread. Marking client-side rather than
  // in the retrieve endpoint: a task fetch (list refresh, poll, prefetch)
  // isn't a view.

  const { mutate: markTasksRead } = useMarkTaskActivityRead();
  useEffect(() => {
    markTasksRead([{ task_id: taskId, seen_before: new Date().toISOString() }]);
  }, [markTasksRead, taskId]);

  useHotkeys("mod+p", () => openFilePicker(), {
    enableOnContentEditable: true,
    enableOnFormTags: true,
    preventDefault: true,
  });

  useRepoFileWatcher(effectiveRepoPath ?? null, taskId);

  useBlurOnEscape();
  useWorkspaceEvents(taskId);

  const [editingTaskId, setEditingTaskId] = useState<string | null>(null);
  const isEditingTitle = editingTaskId === taskId;
  const { renameTask } = useRenameTask();

  const handleTitleEditSubmit = useCallback(
    async (newTitle: string) => {
      setEditingTaskId(null);

      try {
        await renameTask({
          taskId,
          currentTitle: task.title,
          newTitle,
        });
      } catch (error) {
        log.error("Failed to rename task", error);
      }
    },
    [renameTask, task.title, taskId],
  );

  const handleTitleEditCancel = useCallback(() => {
    setEditingTaskId(null);
  }, []);
  // Inside a channel the thread also gets a "copy link" share affordance.
  // Memoized so the headerContent memo below isn't busted by unrelated renders.
  const trailing = useMemo(
    () =>
      channelId ? (
        <CopyThreadLinkButton channelId={channelId} taskId={taskId} />
      ) : null,
    [channelId, taskId],
  );
  const workspace = useWorkspace(taskId);
  const workspaceMode = workspace?.mode;
  const headerContent = useMemo(
    () =>
      // Inside a channel, prefix the editable title with the channel
      // breadcrumb ("# channel / title"); the plain Code view keeps the bare
      // title. Both share the same inline-rename editor.
      channelName ? (
        <ChannelBreadcrumb
          channelName={channelName}
          channelId={channelId}
          leafIcon={
            <span className="flex items-center gap-1.5">
              <TaskHeaderMark
                task={task}
                mode={workspaceMode}
                checkoutPath={effectiveRepoPath}
              />
              <CustomImageBadge task={task} />
            </span>
          }
          leafLabel={task.title}
          editScopeKey={taskId}
          onRename={handleTitleEditSubmit}
          leafTrailing={
            <span className="flex shrink-0 items-center gap-0">
              <TaskHeaderMarks task={task} />
              {trailing}
            </span>
          }
        />
      ) : (
        <Flex align="center" justify="between" gap="2" width="100%">
          {isEditingTitle ? (
            <HeaderTitleEditor
              initialTitle={task.title}
              onSubmit={handleTitleEditSubmit}
              onCancel={handleTitleEditCancel}
            />
          ) : (
            <Flex align="center" gap="2" minWidth="0">
              <TaskHeaderMark
                task={task}
                mode={workspaceMode}
                checkoutPath={effectiveRepoPath}
              />
              <CustomImageBadge task={task} />
              <Tooltip content={task.title} side="bottom" delayDuration={300}>
                <Text
                  truncate
                  className="no-drag min-w-0 font-medium text-[13px]"
                  onDoubleClick={() => setEditingTaskId(taskId)}
                >
                  {task.title}
                </Text>
              </Tooltip>
              <TaskHeaderMarks task={task} />
            </Flex>
          )}
          {trailing}
        </Flex>
      ),
    [
      channelName,
      channelId,
      task,
      trailing,
      isEditingTitle,
      workspaceMode,
      effectiveRepoPath,
      taskId,
      handleTitleEditSubmit,
      handleTitleEditCancel,
    ],
  );

  useSetHeaderContent(headerContent);

  const reviewMode = useReviewNavigationStore(
    (s) => s.reviewModes[taskId] ?? "closed",
  );
  const isCloud =
    workspace?.mode === "cloud" || task.latest_run?.environment === "cloud";

  // Where the shared right panel draws the review, the in-task pane stands
  // down rather than drawing it a second time.
  const inRightPanel = useReviewInRightPanel();
  const isReviewOpen = !inRightPanel && reviewMode !== "closed";
  const isExpanded = !inRightPanel && reviewMode === "expanded";

  // Keyed off the review mode rather than this pane, so a review open in the
  // right panel keeps the diff queries it is drawing from. A drag on that
  // panel's handle passes through "closed" and back within one gesture, so the
  // clear waits for the drag to end rather than emptying the cache under a
  // review that is still on screen.
  const isDraggingRightPanel = useRightPanelStore((s) => s.isResizing);
  useEffect(() => {
    if (reviewMode !== "closed" || isDraggingRightPanel) return;
    clearGitReviewQueries();
  }, [reviewMode, isDraggingRightPanel]);

  const containerRef = useRef<HTMLDivElement>(null);
  const [reviewWidth, setReviewWidth] = useState<number | null>(null);
  const isDragging = useRef(false);

  const handleResizeStart = useCallback(
    (e: React.MouseEvent) => {
      e.preventDefault();
      isDragging.current = true;

      const startX = e.clientX;
      const container = containerRef.current;
      if (!container) return;

      const containerRect = container.getBoundingClientRect();
      const startWidth = reviewWidth ?? containerRect.width * 0.5;

      const onMouseMove = (moveEvent: MouseEvent) => {
        const delta = startX - moveEvent.clientX;
        const maxWidth = Math.max(
          MIN_REVIEW_WIDTH,
          containerRect.width * 0.5,
          containerRect.width - MIN_CHAT_WIDTH,
        );
        const newWidth = Math.min(
          maxWidth,
          Math.max(MIN_REVIEW_WIDTH, startWidth + delta),
        );
        setReviewWidth(newWidth);
      };

      const onMouseUp = () => {
        isDragging.current = false;
        document.removeEventListener("mousemove", onMouseMove);
        document.removeEventListener("mouseup", onMouseUp);
        document.body.style.cursor = "";
        document.body.style.userSelect = "";
      };

      document.body.style.cursor = "col-resize";
      document.body.style.userSelect = "none";
      document.addEventListener("mousemove", onMouseMove);
      document.addEventListener("mouseup", onMouseUp);
    },
    [reviewWidth],
  );

  return (
    <Box data-task-detail-id={taskId} height="100%" ref={containerRef}>
      <Flex height="100%">
        <Box className={`min-w-0 flex-1 ${isExpanded ? "hidden" : ""}`}>
          <PanelLayout taskId={taskId} task={task} />
        </Box>

        {isReviewOpen && !isExpanded && (
          <Box
            onMouseDown={handleResizeStart}
            className="z-[1] w-[4px] shrink-0 cursor-col-resize border-l border-l-(--gray-6) bg-transparent transition-colors hover:bg-accent-6 active:bg-accent-8"
          />
        )}

        {isReviewOpen && (
          <Box
            style={{
              flex: isExpanded ? 1 : undefined,
              width: isExpanded
                ? undefined
                : reviewWidth
                  ? `${reviewWidth}px`
                  : "50%",
              minWidth: `${MIN_REVIEW_WIDTH}px`,
            }}
            className="h-full"
          >
            {isCloud ? (
              <CloudReviewPage task={task} />
            ) : (
              <ReviewPage task={task} />
            )}
          </Box>
        )}
      </Flex>
      {archiveDialog}
    </Box>
  );
}
