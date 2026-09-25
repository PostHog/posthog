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
import { Tooltip } from "@posthog/ui/primitives/Tooltip";
import { track } from "@posthog/ui/shell/analytics";
import { previewLabel } from "./previewLabel";
import { useTaskPreviewPorts } from "./useTaskPreviewPorts";

export function TaskPreviewButton({ task }: { task: Task }) {
  const previews = useTaskPreviewPorts(task);
  const openPreviewTab = usePanelLayoutStore((state) => state.openPreviewTab);

  if (!previews || previews.ports.length === 0) return null;
  const { runId, ports } = previews;

  const open = (port: TaskRunExposedPort) => {
    track(ANALYTICS_EVENTS.TASK_PREVIEW_OPENED, {
      port_count: ports.length,
      source: "header",
      placement: "main",
    });
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
