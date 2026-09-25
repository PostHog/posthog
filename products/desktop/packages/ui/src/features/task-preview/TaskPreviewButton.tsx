import { Globe } from "@phosphor-icons/react";
import {
  Button,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@posthog/quill";
import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import type { Task, TaskRunExposedPort } from "@posthog/shared/domain-types";
import { usePanelLayoutStore } from "@posthog/ui/features/panels/panelLayoutStore";
import { useIsCloudTask } from "@posthog/ui/features/workspace/useWorkspace";
import { Tooltip } from "@posthog/ui/primitives/Tooltip";
import { track } from "@posthog/ui/shell/analytics";
import { previewLabel } from "./previewLabel";
import { useTaskPreviewEnabled } from "./useTaskPreviewEnabled";
import { useTaskRunExposedPorts } from "./useTaskRunExposedPorts";

export function TaskPreviewButton({ task }: { task: Task }) {
  const enabled = useTaskPreviewEnabled();
  const isCloud = useIsCloudTask(task);
  const runId = task.latest_run?.id;
  const ports = useTaskRunExposedPorts(task.id, runId, enabled && isCloud);
  const openPreviewTab = usePanelLayoutStore((state) => state.openPreviewTab);

  if (!enabled || !isCloud || !runId || ports.length === 0) return null;

  const open = (port: TaskRunExposedPort) => {
    track(ANALYTICS_EVENTS.TASK_PREVIEW_OPENED, { port_count: ports.length });
    openPreviewTab(task.id, {
      runId,
      port: port.port,
      label: previewLabel(port),
    });
  };

  if (ports.length === 1) {
    const [port] = ports;
    return (
      <Tooltip content={`Open ${previewLabel(port)}`} side="bottom">
        <Button
          size="sm"
          variant="outline"
          data-attr="task-preview-open"
          onClick={() => open(port)}
        >
          <Globe size={14} />
          Preview
        </Button>
      </Tooltip>
    );
  }

  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        render={
          <Button size="sm" variant="outline" data-attr="task-preview-menu">
            <Globe size={14} />
            Preview
          </Button>
        }
      />
      <DropdownMenuContent align="end" side="bottom" sideOffset={4}>
        {ports.map((port) => (
          <DropdownMenuItem
            key={port.port}
            data-attr="task-preview-open"
            onClick={() => open(port)}
          >
            <span className="truncate">{previewLabel(port)}</span>
            <span className="ml-auto text-muted-foreground">:{port.port}</span>
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
