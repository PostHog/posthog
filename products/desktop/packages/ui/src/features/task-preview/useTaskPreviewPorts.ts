import type { Task, TaskRunExposedPort } from "@posthog/shared/domain-types";
import { useSessionSelector } from "@posthog/ui/features/sessions/sessionStore";
import {
  isCloudTask,
  useWorkspace,
} from "@posthog/ui/features/workspace/useWorkspace";
import { useMemo } from "react";
import { useExposedPortsFromEvents } from "./exposedPortsFromEvents";
import { useTaskPreviewEnabled } from "./useTaskPreviewEnabled";
import { useTaskRunExposedPorts } from "./useTaskRunExposedPorts";

export type TaskPreviewPorts = { runId: string; ports: TaskRunExposedPort[] };

const NO_EVENTS: never[] = [];
export const LOCAL_PREVIEW_RUN_ID = "local";

export function useTaskPreviewPorts(
  task: Task | undefined,
): TaskPreviewPorts | null {
  const enabled = useTaskPreviewEnabled();
  const taskId = task?.id ?? "";
  const workspace = useWorkspace(taskId);
  const isCloud = task ? isCloudTask(task, workspace) : false;
  const runId = task?.latest_run?.id;
  const cloudPorts = useTaskRunExposedPorts(
    taskId,
    runId,
    enabled && isCloud && !!task,
  );
  const events = useSessionSelector(taskId, (session) => session?.events);
  const localPorts = useExposedPortsFromEvents(
    enabled && !isCloud ? (events ?? NO_EVENTS) : NO_EVENTS,
  );
  return useMemo(() => {
    if (!enabled || !task) return null;
    if (isCloud) {
      return runId ? { runId, ports: cloudPorts } : null;
    }
    return { runId: runId ?? LOCAL_PREVIEW_RUN_ID, ports: localPorts };
  }, [enabled, task, isCloud, runId, cloudPorts, localPorts]);
}
