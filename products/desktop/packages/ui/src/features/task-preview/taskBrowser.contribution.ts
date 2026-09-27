import type { PanelNode } from "@posthog/core/panels/panelTypes";
import type { Contribution } from "@posthog/di/contribution";
import {
  type ITaskBrowserHost,
  TASK_BROWSER_HOST,
} from "@posthog/platform/task-browser";
import {
  type TaskLayout,
  usePanelLayoutStore,
} from "@posthog/ui/features/panels/panelLayoutStore";
import { inject, injectable, optional } from "inversify";
import { useTaskBrowserPermissionStore } from "./taskBrowserPermissionStore";
import { closeAgentBrowserTab, openAgentBrowserTab } from "./taskBrowserTabs";

function collectBrowserTabIds(node: PanelNode, ids: Set<string>): void {
  if (node.type === "group") {
    for (const child of node.children) collectBrowserTabIds(child, ids);
    return;
  }
  for (const tab of node.content.tabs) {
    if (tab.data.type === "browser") ids.add(tab.data.browserId);
  }
}

export function browserTabIds(
  layouts: Record<string, TaskLayout>,
): Set<string> {
  const ids = new Set<string>();
  for (const layout of Object.values(layouts)) {
    collectBrowserTabIds(layout.panelTree, ids);
  }
  return ids;
}

@injectable()
export class TaskBrowserContribution implements Contribution {
  private unsubscribers: Array<() => void> = [];

  constructor(
    @inject(TASK_BROWSER_HOST)
    @optional()
    private readonly host: ITaskBrowserHost | null = null,
  ) {}

  start(): void {
    this.stop();
    const host = this.host;
    if (!host) return;
    const permissions = useTaskBrowserPermissionStore.getState();
    this.unsubscribers = [
      host.onOpenRequest(openAgentBrowserTab),
      host.onCloseRequest(closeAgentBrowserTab),
      host.onPermissionRequest(permissions.enqueue),
      host.onPermissionSettled(permissions.remove),
      usePanelLayoutStore.subscribe((state, previous) => {
        if (state.taskLayouts === previous.taskLayouts) return;
        const open = browserTabIds(state.taskLayouts);
        for (const browserId of browserTabIds(previous.taskLayouts)) {
          if (!open.has(browserId)) void host.forgetTab(browserId);
        }
      }),
    ];
  }

  stop(): void {
    for (const unsubscribe of this.unsubscribers) unsubscribe();
    this.unsubscribers = [];
  }
}
