import type { Contribution } from "@posthog/di/contribution";
import {
  IMPERATIVE_QUERY_CLIENT,
  type ImperativeQueryClient,
} from "@posthog/ui/shell/queryClient";
import { inject, injectable } from "inversify";
import {
  taskPreviewPortsQueryKey,
  taskPreviewPortsService,
} from "./taskPreviewPortsService";

@injectable()
export class TaskPreviewPortsContribution implements Contribution {
  private unwatch: (() => void) | null = null;

  constructor(
    @inject(IMPERATIVE_QUERY_CLIENT)
    private readonly queryClient: ImperativeQueryClient,
  ) {}

  start(): void {
    this.unwatch?.();
    this.unwatch = taskPreviewPortsService.watch((taskId) => {
      void this.queryClient.invalidateQueries({
        queryKey: taskPreviewPortsQueryKey(taskId ?? undefined),
      });
    });
  }
}
