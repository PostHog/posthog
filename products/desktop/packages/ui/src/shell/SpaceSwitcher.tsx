import type { TaskData } from "@posthog/core/sidebar/sidebarData.types";
import type { Task } from "@posthog/shared/domain-types";
import { SHORTCUTS } from "@posthog/ui/features/command/keyboard-shortcuts";
import { useCallback, useMemo } from "react";
import { useHotkeys } from "react-hotkeys-hook";

const SPACE_HOTKEY_OPTIONS = {
  enableOnFormTags: true,
  enableOnContentEditable: true,
  preventDefault: false,
} as const;

function isInputWithContent(): boolean {
  const el = document.activeElement;
  if (!el) return false;
  if (el instanceof HTMLInputElement || el instanceof HTMLTextAreaElement) {
    return el.value.length > 0;
  }
  if (el instanceof HTMLElement && el.isContentEditable) {
    return (el.textContent?.length ?? 0) > 0;
  }
  return false;
}

interface SpaceSwitcherProps {
  tasks: TaskData[];
  activeTaskId: string | null;
  allTasks: Task[];
  isOnNewTask: boolean;
  onNavigateToTask: (task: Task) => void;
  onNewTask: () => void;
}

export function SpaceSwitcher({
  tasks,
  activeTaskId,
  allTasks,
  isOnNewTask,
  onNavigateToTask,
  onNewTask,
}: SpaceSwitcherProps) {
  const taskById = useMemo(() => {
    const map = new Map<string, Task>();
    for (const task of allTasks) {
      map.set(task.id, task);
    }
    return map;
  }, [allTasks]);

  // Slot 0 = new task, slots 1..n = tasks, -1 = no active slot
  const totalSlots = tasks.length + 1;
  const currentSlot = isOnNewTask
    ? 0
    : activeTaskId !== null
      ? tasks.findIndex((t) => t.id === activeTaskId) + 1
      : -1;

  const navigateToSlot = useCallback(
    (slot: number) => {
      if (slot === 0) {
        onNewTask();
      } else {
        const taskData = tasks[slot - 1];
        const task = taskData ? taskById.get(taskData.id) : undefined;
        if (task) onNavigateToTask(task);
      }
    },
    [tasks, taskById, onNavigateToTask, onNewTask],
  );

  const navigatePrev = useCallback(() => {
    if (tasks.length === 0) return;
    if (currentSlot === -1) {
      navigateToSlot(totalSlots - 1);
      return;
    }
    const prev = currentSlot <= 0 ? totalSlots - 1 : currentSlot - 1;
    navigateToSlot(prev);
  }, [tasks.length, totalSlots, currentSlot, navigateToSlot]);

  const navigateNext = useCallback(() => {
    if (tasks.length === 0) return;
    if (currentSlot === -1) {
      navigateToSlot(0);
      return;
    }
    const next = currentSlot >= totalSlots - 1 ? 0 : currentSlot + 1;
    navigateToSlot(next);
  }, [tasks.length, totalSlots, currentSlot, navigateToSlot]);

  useHotkeys(
    SHORTCUTS.SPACE_UP,
    (e) => {
      if (isInputWithContent()) return;
      e.preventDefault();
      navigatePrev();
    },
    SPACE_HOTKEY_OPTIONS,
    [navigatePrev],
  );
  useHotkeys(
    SHORTCUTS.SPACE_DOWN,
    (e) => {
      if (isInputWithContent()) return;
      e.preventDefault();
      navigateNext();
    },
    SPACE_HOTKEY_OPTIONS,
    [navigateNext],
  );

  return null;
}
