import {
  SESSION_SERVICE,
  type SessionService,
} from "@posthog/core/sessions/sessionService";
import { useService } from "@posthog/di/react";
import { useHostTRPC } from "@posthog/host-router/react";
import { PROJECT_BLUEBIRD_FLAG } from "@posthog/shared";
import type { Task } from "@posthog/shared/domain-types";
import { useReviewNavigationStore } from "@posthog/ui/features/code-review/reviewNavigationStore";
import { SHORTCUTS } from "@posthog/ui/features/command/keyboard-shortcuts";
import { useFeatureFlag } from "@posthog/ui/features/feature-flags/useFeatureFlag";
import { useFolders } from "@posthog/ui/features/folders/useFolders";
import { usePanelLayoutStore } from "@posthog/ui/features/panels/panelLayoutStore";
import { openSettings } from "@posthog/ui/features/settings/hooks/useOpenSettings";
import { useSidebarStore } from "@posthog/ui/features/sidebar/sidebarStore";
import { useSidebarData } from "@posthog/ui/features/sidebar/useSidebarData";
import { useVisualTaskOrder } from "@posthog/ui/features/sidebar/useVisualTaskOrder";
import { useTasks } from "@posthog/ui/features/tasks/useTasks";
import { useFocusWorkspace } from "@posthog/ui/features/workspace/useFocusWorkspace";
import { useWorkspaces } from "@posthog/ui/features/workspace/useWorkspace";
import { shipIt } from "@posthog/ui/primitives/confetti";
import {
  goBackInHistory,
  goForwardInHistory,
  navigateToFolderSettings,
  navigateToInbox,
} from "@posthog/ui/router/navigationBridge";
import { useAppView } from "@posthog/ui/router/useAppView";
import { openTask, openTaskInput } from "@posthog/ui/router/useOpenTask";
import { useCommandMenuStore } from "@posthog/ui/shell/commandMenuStore";
import { logger } from "@posthog/ui/shell/logger";
import { useRendererWindowFocusStore } from "@posthog/ui/shell/rendererWindowFocusStore";
import { clearApplicationStorage } from "@posthog/ui/utils/clearStorage";
import { useSubscription } from "@trpc/tanstack-react-query";
import { useCallback, useEffect, useMemo, useRef } from "react";
import { useHotkeys } from "react-hotkeys-hook";

interface GlobalEventHandlersProps {
  onToggleCommandMenu: () => void;
  onToggleShortcutsSheet: () => void;
}

export function GlobalEventHandlers({
  onToggleCommandMenu,
  onToggleShortcutsSheet,
}: GlobalEventHandlersProps) {
  const trpcReact = useHostTRPC();
  const sessionService = useService<SessionService>(SESSION_SERVICE);
  const commandMenuOpen = useCommandMenuStore((s) => s.isOpen);
  const openSettingsDialog = openSettings;
  const view = useAppView();
  const goBack = goBackInHistory;
  const goForward = goForwardInHistory;
  const { folders, loadFolders } = useFolders();
  const { data: workspaces = {} } = useWorkspaces();
  const clearAllLayouts = usePanelLayoutStore((state) => state.clearAllLayouts);
  const toggleLeftSidebar = useSidebarStore((state) => state.toggle);
  const setReviewMode = useReviewNavigationStore(
    (state) => state.setReviewMode,
  );
  const getReviewMode = useReviewNavigationStore(
    (state) => state.getReviewMode,
  );

  const currentTaskId = view.type === "task-detail" ? view.taskId : undefined;
  const { workspace: currentWorkspace, handleToggleFocus } = useFocusWorkspace(
    currentTaskId ?? "",
  );
  const isWorktreeTask = currentWorkspace?.mode === "worktree";

  const { data: allTasks = [] } = useTasks();
  const sidebarData = useSidebarData({ activeView: view });
  const visualTaskOrder = useVisualTaskOrder(sidebarData);

  // With channels on, mod+1-9 belongs to the browser tab strip (it switches to
  // the Nth tab). Yield those keys so task-switching only owns them in the Code
  // nav; the strip's own handler is gated on the same flag.
  const bluebirdEnabled = useFeatureFlag(
    PROJECT_BLUEBIRD_FLAG,
    import.meta.env.DEV,
  );
  const channelsEnabled =
    useSidebarStore((s) => s.channelsEnabled) && bluebirdEnabled;

  const taskById = useMemo(() => {
    const map = new Map<string, Task>();
    for (const task of allTasks) {
      map.set(task.id, task);
    }
    return map;
  }, [allTasks]);

  const handleSwitchTask = useCallback(
    (index: number) => {
      const taskData = visualTaskOrder[index - 1];
      const task = taskData ? taskById.get(taskData.id) : undefined;
      if (task) void openTask(task);
    },
    [visualTaskOrder, taskById],
  );

  const handlePrevTask = useCallback(() => {
    if (visualTaskOrder.length === 0) return;
    if (view.type !== "task-detail" || !view.taskId) {
      const lastTaskData = visualTaskOrder[visualTaskOrder.length - 1];
      const task = lastTaskData ? taskById.get(lastTaskData.id) : undefined;
      if (task) void openTask(task);
      return;
    }
    const currentIndex = visualTaskOrder.findIndex((t) => t.id === view.taskId);
    const prevIndex =
      currentIndex <= 0 ? visualTaskOrder.length - 1 : currentIndex - 1;
    const prevTaskData = visualTaskOrder[prevIndex];
    const task = prevTaskData ? taskById.get(prevTaskData.id) : undefined;
    if (task) void openTask(task);
  }, [visualTaskOrder, taskById, view]);

  const handleNextTask = useCallback(() => {
    if (visualTaskOrder.length === 0) return;
    if (view.type !== "task-detail" || !view.taskId) {
      const firstTaskData = visualTaskOrder[0];
      const task = firstTaskData ? taskById.get(firstTaskData.id) : undefined;
      if (task) void openTask(task);
      return;
    }
    const currentIndex = visualTaskOrder.findIndex((t) => t.id === view.taskId);
    const nextIndex =
      currentIndex >= visualTaskOrder.length - 1 ? 0 : currentIndex + 1;
    const nextTaskData = visualTaskOrder[nextIndex];
    const task = nextTaskData ? taskById.get(nextTaskData.id) : undefined;
    if (task) void openTask(task);
  }, [visualTaskOrder, taskById, view]);

  const handleOpenSettings = useCallback(() => {
    openSettingsDialog();
  }, [openSettingsDialog]);

  const handleFocusTaskMode = useCallback((data?: unknown) => {
    if (!data) return;
    openTaskInput();
  }, []);

  const handleResetLayout = useCallback(
    (data?: unknown) => {
      if (!data) return;
      clearAllLayouts();
      window.location.reload();
    },
    [clearAllLayouts],
  );

  const handleClearStorage = useCallback((data?: unknown) => {
    if (!data) return;
    clearApplicationStorage();
  }, []);

  const handleInvalidateToken = useCallback((data?: unknown) => {
    if (!data) return;
    const log = logger.scope("global-event-handlers");
    log.info("Main access token invalidated for testing");
  }, []);

  const globalOptions = {
    enableOnFormTags: true,
    enableOnContentEditable: true,
    preventDefault: true,
  } as const;

  useHotkeys(SHORTCUTS.COMMAND_MENU, onToggleCommandMenu, {
    ...globalOptions,
    enabled: !commandMenuOpen,
  });
  useHotkeys(SHORTCUTS.NEW_TASK, handleFocusTaskMode, globalOptions);
  useHotkeys(SHORTCUTS.SETTINGS, handleOpenSettings, globalOptions);
  useHotkeys(SHORTCUTS.GO_BACK, goBack, globalOptions);
  useHotkeys(SHORTCUTS.GO_FORWARD, goForward, globalOptions);
  // mod+left/right means jump to line start/end inside inputs and editors, so
  // the arrow variants skip enableOnFormTags/enableOnContentEditable.
  useHotkeys(SHORTCUTS.GO_BACK_ALT, goBack, { preventDefault: true });
  useHotkeys(SHORTCUTS.GO_FORWARD_ALT, goForward, { preventDefault: true });
  const handleToggleReview = useCallback(() => {
    if (!currentTaskId) return;
    const mode = getReviewMode(currentTaskId);
    setReviewMode(currentTaskId, mode === "closed" ? "split" : "closed");
  }, [currentTaskId, getReviewMode, setReviewMode]);

  useHotkeys(
    SHORTCUTS.RELOAD_WINDOW,
    () => window.location.reload(),
    globalOptions,
  );
  useHotkeys(SHORTCUTS.TOGGLE_LEFT_SIDEBAR, toggleLeftSidebar, globalOptions);
  useHotkeys(SHORTCUTS.TOGGLE_REVIEW_PANEL, handleToggleReview, globalOptions);
  useHotkeys(SHORTCUTS.SHORTCUTS_SHEET, onToggleShortcutsSheet, globalOptions);
  useHotkeys(SHORTCUTS.INBOX, navigateToInbox, globalOptions);
  useHotkeys(SHORTCUTS.PREV_TASK, handlePrevTask, globalOptions, [
    handlePrevTask,
  ]);
  useHotkeys(SHORTCUTS.NEXT_TASK, handleNextTask, globalOptions, [
    handleNextTask,
  ]);

  useHotkeys(
    SHORTCUTS.TOGGLE_FOCUS,
    handleToggleFocus,
    {
      ...globalOptions,
      enabled: !!currentTaskId && isWorktreeTask,
    },
    [handleToggleFocus],
  );

  // Task switching with mod+1-9 — off when channels are on (the browser tab
  // strip claims those keys to switch tabs by index).
  useHotkeys(
    SHORTCUTS.SWITCH_TASK,
    (event, handler) => {
      if (event.ctrlKey && !event.metaKey) return;

      const keyPressed = handler.keys?.[0];
      if (!keyPressed) return;
      const index = parseInt(keyPressed, 10);
      handleSwitchTask(index);
    },
    { ...globalOptions, enabled: !channelsEnabled },
    [handleSwitchTask],
  );

  // Konami code confetti
  const konamiProgressRef = useRef(0);
  useEffect(() => {
    const sequence = [
      "ArrowUp",
      "ArrowUp",
      "ArrowDown",
      "ArrowDown",
      "ArrowLeft",
      "ArrowRight",
      "ArrowLeft",
      "ArrowRight",
      "b",
      "a",
    ];
    const handleKey = (event: KeyboardEvent) => {
      const key = event.key.length === 1 ? event.key.toLowerCase() : event.key;
      const expected = sequence[konamiProgressRef.current];
      if (key === expected) {
        konamiProgressRef.current += 1;
        if (konamiProgressRef.current === sequence.length) {
          konamiProgressRef.current = 0;
          shipIt();
        }
      } else {
        konamiProgressRef.current = key === sequence[0] ? 1 : 0;
      }
    };
    window.addEventListener("keydown", handleKey);
    return () => {
      window.removeEventListener("keydown", handleKey);
    };
  }, []);

  // Mouse back/forward buttons
  useEffect(() => {
    const handleMouseButton = (event: MouseEvent) => {
      if (event.button === 3) {
        event.preventDefault();
        goBack();
      } else if (event.button === 4) {
        event.preventDefault();
        goForward();
      }
    };

    window.addEventListener("mouseup", handleMouseButton);
    return () => {
      window.removeEventListener("mouseup", handleMouseButton);
    };
  }, [goBack, goForward]);

  useEffect(() => {
    const handleFocus = () => {
      loadFolders();
      sessionService.retryUnhealthyCloudSessions();
    };
    window.addEventListener("focus", handleFocus);
    return () => window.removeEventListener("focus", handleFocus);
  }, [loadFolders, sessionService]);

  // Freeze perpetual CSS animations while the window is backgrounded (see the
  // `.ph-window-blurred` rule in globals.css). Driven by the shared focus store
  // so we don't add yet another blur/focus listener.
  const windowFocused = useRendererWindowFocusStore((s) => s.focused);
  useEffect(() => {
    document.body.classList.toggle("ph-window-blurred", !windowFocused);
    return () => document.body.classList.remove("ph-window-blurred");
  }, [windowFocused]);

  // Check if current task's folder became invalid (e.g., moved while app was open)
  useEffect(() => {
    if (view.type !== "task-detail" || !view.taskId) return;

    const workspace = workspaces[view.taskId];
    if (!workspace?.folderId) return;

    const folder = folders.find((f) => f.id === workspace.folderId);
    if (folder && folder.exists === false) {
      navigateToFolderSettings(folder.id);
    }
  }, [view, folders, workspaces]);

  useSubscription(
    trpcReact.ui.onOpenSettings.subscriptionOptions(undefined, {
      onData: handleOpenSettings,
    }),
  );

  useSubscription(
    trpcReact.ui.onNewTask.subscriptionOptions(undefined, {
      onData: handleFocusTaskMode,
    }),
  );

  useSubscription(
    trpcReact.ui.onResetLayout.subscriptionOptions(undefined, {
      onData: handleResetLayout,
    }),
  );

  useSubscription(
    trpcReact.ui.onClearStorage.subscriptionOptions(undefined, {
      onData: handleClearStorage,
    }),
  );

  useSubscription(
    trpcReact.ui.onInvalidateToken.subscriptionOptions(undefined, {
      onData: handleInvalidateToken,
    }),
  );

  return null;
}
