import {
  type TaskInputReportAssociation,
  useTaskInputPrefillStore,
} from "@posthog/ui/features/task-detail/stores/taskInputPrefillStore";
import { useRouterState } from "@tanstack/react-router";
import { useMemo } from "react";
import { getCurrentMatches } from "./navigationBridge";

export type AppViewType =
  | "task-detail"
  | "task-pending"
  | "task-input"
  | "folder-settings"
  | "activity"
  | "inbox"
  | "agents"
  | "loops"
  | "archived"
  | "command-center"
  | "skills"
  | "mcp-servers"
  | "settings";

export interface AppView {
  type: AppViewType;
  taskId?: string;
  folderId?: string;
  pendingTaskKey?: string;
  taskInputRequestId?: string;
  initialPrompt?: string;
  initialCloudRepository?: string;
  initialModel?: string;
  initialMode?: string;
  folderRunEnvironment?: "local" | "cloud";
  reportAssociation?: TaskInputReportAssociation;
}

type Match = { routeId: string; params: Record<string, string | undefined> };

function deriveFromMatches(matches: Match[]): AppView {
  const last = matches[matches.length - 1];
  if (!last) return { type: "task-input" };

  switch (last.routeId) {
    // Both the /code task detail and the channels-space task detail render the
    // same task-detail view, so consumers (active-state highlighting, archive's
    // navigate-away-if-active check) treat them identically.
    case "/code/tasks/$taskId":
    case "/website/$channelId/tasks/$taskId": {
      const taskId = last.params.taskId;
      if (!taskId) return { type: "task-input" };
      // Intentionally no `data` snapshot: consumers read live task state via
      // their own query hooks (e.g. useTasks) keyed on `taskId`.
      return { type: "task-detail", taskId };
    }
    case "/code/tasks/pending/$key":
      return { type: "task-pending", pendingTaskKey: last.params.key };
    // Channels-space new-task screen — same task-input view (and prefill merge
    // below) as the /code/ index, so the New task item highlights identically.
    case "/website/new":
      return { type: "task-input" };
    case "/folders/$folderId":
      return { type: "folder-settings", folderId: last.params.folderId };
    case "/website/activity":
      return { type: "activity" };
    case "/code/inbox":
      return { type: "inbox" };
    case "/code/agents":
      return { type: "agents" };
    case "/code/loops":
      return { type: "loops" };
    case "/code/archived":
      return { type: "archived" };
    case "/command-center":
    case "/website/command-center":
      return { type: "command-center" };
    case "/skills":
    case "/website/skills":
      return { type: "skills" };
    case "/mcp-servers":
    case "/website/mcp-servers":
      return { type: "mcp-servers" };
    case "/settings/$category":
    case "/settings/":
      return { type: "settings" };
    default:
      if (last.routeId.startsWith("/code/inbox")) {
        return { type: "inbox" };
      }
      // /code/agents is now an Outlet layout; the view lives at the index
      // child (/code/agents/) and scout detail routes nest deeper, so match
      // the whole subtree rather than only the bare layout route.
      if (last.routeId.startsWith("/code/agents")) {
        return { type: "agents" };
      }
      // /code/loops covers the list, create form, and the per-loop detail /
      // edit subtree ($loopId is an Outlet layout), so match the prefix.
      if (last.routeId.startsWith("/code/loops")) {
        return { type: "loops" };
      }
      return { type: "task-input" };
  }
}

/**
 * Single source of truth for the current view. Replaces the
 * pre-router `useNavigationStore((s) => s.view)` pattern.
 *
 * The returned object is memoized on the route's primitive values so its
 * identity is stable across unrelated re-renders. This matters: the old
 * navigationStore handed out a stable `view` reference, and consumers depend on
 * `[view]` in effects/memos. Returning a fresh object every render turns any
 * such effect into an infinite loop (e.g. SidebarMenu → markViewed → cache
 * write → re-render → repeat), which starves the UI thread.
 */
export function useAppView(): AppView {
  const last = useRouterState({
    select: (s) => {
      const m = s.matches[s.matches.length - 1];
      return m
        ? {
            routeId: m.routeId,
            params: m.params as Record<string, string | undefined>,
          }
        : null;
    },
  });
  const prefill = useTaskInputPrefillStore((s) => s.prefill);

  const routeId = last?.routeId ?? "";
  const taskId = last?.params.taskId;
  const pendingKey = last?.params.key;
  const folderId = last?.params.folderId;

  return useMemo(() => {
    // Rebuild the match from primitives so the memo depends only on stable
    // values — the `last` selector returns a fresh object every render.
    const match = routeId
      ? { routeId, params: { taskId, key: pendingKey, folderId } }
      : null;
    const view = deriveFromMatches(match ? [match] : []);

    // /code/ → merge prefill so the TaskInput screen surfaces transient fields.
    if (view.type === "task-input") {
      return {
        ...view,
        folderId: prefill.folderId,
        initialPrompt: prefill.initialPrompt,
        initialCloudRepository: prefill.initialCloudRepository,
        initialModel: prefill.initialModel,
        initialMode: prefill.initialMode,
        folderRunEnvironment: prefill.folderRunEnvironment,
        reportAssociation: prefill.reportAssociation,
        taskInputRequestId: prefill.requestId,
      };
    }
    return view;
  }, [routeId, taskId, pendingKey, folderId, prefill]);
}

/**
 * Read the current view outside React (event handlers, imperative code).
 * Components should prefer `useAppView()` for proper subscription.
 */
export function getAppViewSnapshot(): AppView {
  const matches = getCurrentMatches() as unknown as Match[];
  return deriveFromMatches(matches);
}
