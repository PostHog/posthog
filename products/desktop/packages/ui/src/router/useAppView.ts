import type { EditorContent } from "@posthog/core/message-editor/content";
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
  | "home"
  | "inbox"
  | "agents"
  | "loops"
  | "archived"
  | "command-center"
  | "context"
  | "skills"
  | "mcp-servers"
  | "settings";

export interface AppView {
  type: AppViewType;
  taskId?: string;
  folderId?: string;
  folderRepository?: string;
  pendingTaskKey?: string;
  taskInputRequestId?: string;
  initialPrompt?: string;
  initialContent?: EditorContent;
  recoveredFromKey?: string;
  initialCloudRepository?: string;
  initialModel?: string;
  initialMode?: string;
  folderRunEnvironment?: "local" | "cloud";
  reportAssociation?: TaskInputReportAssociation;
}

type Match = { fullPath: string; params: Record<string, string | undefined> };

function deriveFromMatches(matches: Match[]): AppView {
  const last = matches[matches.length - 1];
  if (!last) return { type: "task-input" };

  switch (last.fullPath) {
    // The unscoped task detail and the space-scoped one render the same view, so
    // consumers (active-state highlighting, archive's navigate-away-if-active
    // check) treat them identically.
    case "/tasks/$taskId":
    case "/spaces/$channelId/tasks/$taskId": {
      const taskId = last.params.taskId;
      if (!taskId) return { type: "task-input" };
      // Intentionally no `data` snapshot: consumers read live task state via
      // their own query hooks (e.g. useTasks) keyed on `taskId`.
      return { type: "task-detail", taskId };
    }
    case "/tasks/pending/$key":
      return { type: "task-pending", pendingTaskKey: last.params.key };
    case "/new":
      return { type: "task-input" };
    case "/folders/$folderId":
      return { type: "folder-settings", folderId: last.params.folderId };
    case "/activity":
      return { type: "activity" };
    case "/":
      return { type: "home" };
    case "/inbox":
      return { type: "inbox" };
    case "/agents":
      return { type: "agents" };
    case "/loops":
      return { type: "loops" };
    case "/archived":
      return { type: "archived" };
    case "/command-center":
      return { type: "command-center" };
    case "/context":
    case "/spaces/context":
      return { type: "context" };
    case "/skills":
      return { type: "skills" };
    case "/mcp-servers":
      return { type: "mcp-servers" };
    case "/settings/$category":
    case "/settings/":
      return { type: "settings" };
    default:
      if (last.fullPath.startsWith("/inbox")) {
        return { type: "inbox" };
      }
      // /agents is an Outlet layout; the view lives at the index child and
      // scout detail routes nest deeper, so match the whole subtree rather
      // than only the bare layout route.
      if (last.fullPath.startsWith("/agents")) {
        return { type: "agents" };
      }
      // /loops covers the list, create form, and the per-loop detail / edit
      // subtree ($loopId is an Outlet layout), so match the prefix.
      if (last.fullPath.startsWith("/loops")) {
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
            fullPath: m.fullPath,
            params: m.params as Record<string, string | undefined>,
          }
        : null;
    },
  });
  const prefill = useTaskInputPrefillStore((s) => s.prefill);

  const fullPath = last?.fullPath ?? "";
  const taskId = last?.params.taskId;
  const pendingKey = last?.params.key;
  const folderId = last?.params.folderId;

  return useMemo(() => {
    // Rebuild the match from primitives so the memo depends only on stable
    // values — the `last` selector returns a fresh object every render.
    const match = fullPath
      ? { fullPath, params: { taskId, key: pendingKey, folderId } }
      : null;
    const view = deriveFromMatches(match ? [match] : []);

    // /code/ → merge prefill so the TaskInput screen surfaces transient fields.
    if (view.type === "task-input") {
      return {
        ...view,
        folderId: prefill.folderId,
        folderRepository: prefill.folderRepository,
        initialPrompt: prefill.initialPrompt,
        initialContent: prefill.initialContent,
        recoveredFromKey: prefill.recoveredFromKey,
        initialCloudRepository: prefill.initialCloudRepository,
        initialModel: prefill.initialModel,
        initialMode: prefill.initialMode,
        folderRunEnvironment: prefill.folderRunEnvironment,
        reportAssociation: prefill.reportAssociation,
        taskInputRequestId: prefill.requestId,
      };
    }
    return view;
  }, [fullPath, taskId, pendingKey, folderId, prefill]);
}

/**
 * Read the current view outside React (event handlers, imperative code).
 * Components should prefer `useAppView()` for proper subscription.
 */
export function getAppViewSnapshot(): AppView {
  const matches = getCurrentMatches() as Match[];
  return deriveFromMatches(matches);
}
