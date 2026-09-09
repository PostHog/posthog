import { buildSketchpadSessionPrompt } from "@posthog/core/sketchpad/sketchpadPrompt";
import {
  TASK_SERVICE,
  type TaskService,
} from "@posthog/core/task-detail/taskService";
import { useService } from "@posthog/di/react";
import type { SketchpadSnapshot } from "@posthog/shared";
import { SKETCHPAD_TASK_ORIGIN } from "@posthog/shared";
import { toastError } from "@posthog/ui/features/notifications/errorDetails";
import { setTaskForSketchpad } from "@posthog/ui/features/sketchpad/hooks/useSketchpadViewportStore";
import { SKETCHPAD_LIBRARY } from "@posthog/ui/features/sketchpad/library/registry";
import { CHAT_START_ERROR } from "@posthog/ui/features/sketchpad/sketchpadCopy";
import { useCallback, useState } from "react";

export interface StartSketchpadSessionArgs {
  sketchpadId: string;
  sketchpadName: string;
  snapshot: SketchpadSnapshot;
  headSeq: number;
  onStarted?: (taskId: string) => void;
}

export interface StartSketchpadSession {
  start: (prompt: string) => Promise<void>;
  pending: boolean;
}

export function useStartSketchpadSession({
  sketchpadId,
  sketchpadName,
  snapshot,
  headSeq,
  onStarted,
}: StartSketchpadSessionArgs): StartSketchpadSession {
  const taskService = useService<TaskService>(TASK_SERVICE);
  const [pending, setPending] = useState(false);

  const start = useCallback(
    async (prompt: string): Promise<void> => {
      const text = prompt.trim();
      if (text.length === 0 || pending) return;
      setPending(true);
      try {
        const result = await taskService.createTask(
          {
            content: buildSketchpadSessionPrompt({
              sketchpadName,
              snapshot,
              headSeq,
              userPrompt: text,
              library: SKETCHPAD_LIBRARY,
            }),
            taskDescription: `Sketchpad: ${sketchpadName}`,
            originProduct: SKETCHPAD_TASK_ORIGIN,
            workspaceMode: "local",
            allowNoRepo: true,
            runtime: "acp",
            adapter: "claude",
            executionMode: "bypassPermissions",
          },
          (output) => {
            setTaskForSketchpad(sketchpadId, output.task.id);
            onStarted?.(output.task.id);
          },
        );
        if (!result.success) {
          toastError(CHAT_START_ERROR, result.error);
        }
      } catch (error) {
        toastError(CHAT_START_ERROR, error);
      } finally {
        setPending(false);
      }
    },
    [
      sketchpadId,
      sketchpadName,
      headSeq,
      onStarted,
      pending,
      snapshot,
      taskService,
    ],
  );

  return { start, pending };
}
