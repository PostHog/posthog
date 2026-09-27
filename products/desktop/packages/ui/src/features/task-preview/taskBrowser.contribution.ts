import type { Contribution } from "@posthog/di/contribution";
import {
  type ITaskBrowserHost,
  TASK_BROWSER_HOST,
} from "@posthog/platform/task-browser";
import { inject, injectable, optional } from "inversify";
import { useTaskBrowserPermissionStore } from "./taskBrowserPermissionStore";
import { closeAgentBrowserTab, openAgentBrowserTab } from "./taskBrowserTabs";

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
    ];
  }

  stop(): void {
    for (const unsubscribe of this.unsubscribers) unsubscribe();
    this.unsubscribers = [];
  }
}
