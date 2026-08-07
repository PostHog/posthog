import type { Contribution } from "@posthog/di/contribution";
import {
  HOST_TRPC_CLIENT,
  type HostTrpcClient,
} from "@posthog/host-router/client";
import type { HostRouter } from "@posthog/host-router/router";
import { createTRPCOptionsProxy } from "@trpc/tanstack-react-query";
import { inject, injectable } from "inversify";
import { toast } from "../../primitives/toast";
import {
  IMPERATIVE_QUERY_CLIENT,
  type ImperativeQueryClient,
} from "../../shell/queryClient";
import { WORKSPACE_QUERY_KEY } from "./identifiers";

/**
 * Boots the global workspace-event listeners once at startup (formerly inline
 * useEffect/useSubscription side effects in App.tsx). Workspace mutations that
 * happen host-side (promote-to-worktree, branch changes, errors) invalidate the
 * shared workspace query so every workspace reader stays in sync, and surface a
 * toast where the user expects feedback.
 */
@injectable()
export class WorkspaceEventsContribution implements Contribution {
  constructor(
    @inject(HOST_TRPC_CLIENT)
    private readonly hostClient: HostTrpcClient,
    @inject(IMPERATIVE_QUERY_CLIENT)
    private readonly queryClient: ImperativeQueryClient,
  ) {}

  start(): void {
    const invalidate = () => {
      void this.queryClient.invalidateQueries({
        queryKey: WORKSPACE_QUERY_KEY,
      });
    };

    this.hostClient.workspace.onError.subscribe(undefined, {
      onData: (data) => {
        toast.error("Workspace error", { description: data.message });
      },
    });

    this.hostClient.workspace.onPromoted.subscribe(undefined, {
      onData: (data) => {
        invalidate();
        toast.info(
          "Task moved to worktree",
          `Task is now working in its own worktree on branch "${data.fromBranch}"`,
        );
      },
    });

    this.hostClient.workspace.onBranchChanged.subscribe(undefined, {
      onData: invalidate,
    });
    this.hostClient.workspace.onLinkedBranchChanged.subscribe(undefined, {
      onData: invalidate,
    });

    const options = createTRPCOptionsProxy<HostRouter>({
      client: this.hostClient,
      queryClient: this.queryClient,
    });
    this.hostClient.workspace.onTaskPrInfoChanged.subscribe(undefined, {
      onData: ({ taskId, prUrl, prUrls, prState }) => {
        this.queryClient.setQueriesData<{
          prState: typeof prState;
          hasDiff: boolean;
        }>(
          {
            ...options.workspace.getTaskPrStatus.pathFilter(),
            predicate: (query) => {
              const [, params] = query.queryKey as [
                unknown,
                { input?: { taskId?: string } } | undefined,
              ];
              return params?.input?.taskId === taskId;
            },
          },
          (prev) => (prev ? { ...prev, prState } : { prState, hasDiff: false }),
        );
        this.queryClient.setQueryData(
          options.workspace.getCachedPrUrl.queryKey({ taskId }),
          { prUrl, prUrls: prUrls ?? [] },
        );
      },
    });
  }
}
