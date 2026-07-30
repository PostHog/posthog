import type { NotificationTarget } from "@posthog/platform/notifications";
import { ANALYTICS_EVENTS } from "@posthog/shared";
import type { SettingsCategory } from "@posthog/ui/features/settings/types";
import { track } from "@posthog/ui/shell/analytics";
import { getRouterOrNull } from "./routerRef";

// This bridge isolates imperative router calls behind a stable API and, by
// reaching the router through `routerRef` (a leaf module) rather than importing
// `./router` directly, keeps itself out of the route-tree import cycle:
//   router.ts → routeTree.gen.ts → __root.tsx → hooks → navigationBridge
// A static `import { router }` here would close that loop and break code-split
// route chunks (TDZ on `rootRouteImport`). See routerRef.ts.
//
// Every call degrades to a no-op / empty read when the router isn't mounted yet
// (early boot, unit tests). These are renderer conveniences — they must never
// throw just because the router singleton hasn't been created.

export function navigateToCode(): void {
  void getRouterOrNull()?.navigate({ to: "/code" });
}

export function navigateToTaskDetail(taskId: string): void {
  void getRouterOrNull()?.navigate({
    to: "/code/tasks/$taskId",
    params: { taskId },
  });
}

export function navigateToPullRequestView(prUrl: string): void {
  void getRouterOrNull()?.navigate({
    to: "/code/pr",
    search: { prUrl },
  });
}

export function navigateToTaskPending(key: string): void {
  void getRouterOrNull()?.navigate({
    to: "/code/tasks/pending/$key",
    params: { key },
  });
}

export function navigateToActivity(): void {
  void getRouterOrNull()?.navigate({ to: "/website/activity" });
}

export function navigateToChannel(channelId: string): void {
  void getRouterOrNull()?.navigate({
    to: "/website/$channelId",
    params: { channelId },
  });
}

export function navigateToChannelTask(channelId: string, taskId: string): void {
  void getRouterOrNull()?.navigate({
    to: "/website/$channelId/tasks/$taskId",
    params: { channelId, taskId },
  });
}

export function navigateToChannelNewTask(channelId: string): void {
  void getRouterOrNull()?.navigate({
    to: "/website/$channelId/new",
    params: { channelId },
  });
}

export function navigateToChannelDashboard(
  channelId: string,
  dashboardId: string,
): void {
  void getRouterOrNull()?.navigate({
    to: "/website/$channelId/dashboards/$dashboardId",
    params: { channelId, dashboardId },
  });
}

export function navigateToFolderSettings(folderId: string): void {
  void getRouterOrNull()?.navigate({
    to: "/folders/$folderId",
    params: { folderId },
  });
}

// The channel-aware "open this notification target" handler, registered by
// useOpenTargetDeepLink (the native-click consumer). Held here so imperative,
// non-React callers — the in-app notification toast's action — open a target
// through the SAME path as a native notification click. Crucially, a task filed
// to a channel resolves to /website/$channelId/tasks/$taskId; direct
// navigateToTaskDetail can't, since it doesn't know the channel.
let openTargetHandler: ((target: NotificationTarget) => void) | null = null;

export function setOpenTargetHandler(
  handler: ((target: NotificationTarget) => void) | null,
): void {
  openTargetHandler = handler;
}

export function openNotificationTarget(target: NotificationTarget): void {
  if (openTargetHandler) {
    openTargetHandler(target);
    return;
  }
  // Fallback when the deep-link handler isn't mounted yet (early boot, tests).
  // Channel context is unavailable here, so a channel task opens under /code —
  // acceptable for this rare gap; the registered handler covers the live app.
  if (target.kind === "task") {
    navigateToTaskDetail(target.taskId);
  } else {
    navigateToChannelDashboard(target.channelId, target.dashboardId);
  }
}

export function navigateToInbox(): void {
  void getRouterOrNull()?.navigate({ to: "/code/inbox" });
}

export function navigateToInboxPullRequestDetail(reportId: string): void {
  void getRouterOrNull()?.navigate({
    to: "/code/inbox/pulls/$reportId",
    params: { reportId },
  });
}

export function navigateToInboxReportDetail(reportId: string): void {
  void getRouterOrNull()?.navigate({
    to: "/code/inbox/reports/$reportId",
    params: { reportId },
  });
}

export function navigateToInboxDismissedDetail(reportId: string): void {
  void getRouterOrNull()?.navigate({
    to: "/code/inbox/dismissed/$reportId",
    params: { reportId },
  });
}

export function navigateToScoutDetail(
  skillSlug: string,
  findingId?: string,
): void {
  void getRouterOrNull()?.navigate({
    to: "/code/agents/scouts/$skillName",
    params: { skillName: skillSlug },
    search: findingId ? { finding: findingId } : {},
  });
}

export function navigateToScoutFindings(): void {
  void getRouterOrNull()?.navigate({ to: "/code/agents/scouts/findings" });
}

export function navigateToLoops(): void {
  void getRouterOrNull()?.navigate({ to: "/code/loops" });
}

export function navigateToNewLoop(): void {
  void getRouterOrNull()?.navigate({ to: "/code/loops/new" });
}

export function navigateToLoopDetail(loopId: string): void {
  void getRouterOrNull()?.navigate({
    to: "/code/loops/$loopId",
    params: { loopId },
  });
}

export function navigateToEditLoop(loopId: string): void {
  void getRouterOrNull()?.navigate({
    to: "/code/loops/$loopId/edit",
    params: { loopId },
  });
}

export function navigateToAgents(): void {
  void getRouterOrNull()?.navigate({ to: "/code/agents" });
}

export function navigateToApproval(requestId: string): void {
  void getRouterOrNull()?.navigate({
    to: "/code/agents/applications/approvals",
    search: { request: requestId },
  });
}

export function navigateToArchived(): void {
  void getRouterOrNull()?.navigate({ to: "/code/archived" });
}

export function navigateToCommandCenter(): void {
  void getRouterOrNull()?.navigate({ to: "/command-center" });
  // Parity with the pre-router navigationStore.navigateToCommandCenter action,
  // which emitted this event; the route component does not track it.
  track(ANALYTICS_EVENTS.COMMAND_CENTER_VIEWED);
}

export function navigateToSkills(): void {
  void getRouterOrNull()?.navigate({ to: "/skills" });
}

export function navigateToMcpServers(): void {
  void getRouterOrNull()?.navigate({ to: "/mcp-servers" });
}

// Channels-space mirrors. These render the same shared views as their /code (or
// top-level) counterparts but under /website, so navigating from the channels
// sidebar keeps the channels chrome instead of switching back to Code. The
// SidebarNavSection picks the right variant based on the active space.

export function navigateToWebsiteNew(): void {
  void getRouterOrNull()?.navigate({ to: "/website/new" });
}

// The Canvas workspace landing (the channels index, where canvases live).
export function navigateToCanvas(): void {
  void getRouterOrNull()?.navigate({ to: "/website" });
}

export function navigateToWebsiteSkills(): void {
  void getRouterOrNull()?.navigate({ to: "/website/skills" });
}

export function navigateToWebsiteMcpServers(): void {
  void getRouterOrNull()?.navigate({ to: "/website/mcp-servers" });
}

export function navigateToWebsiteCommandCenter(): void {
  void getRouterOrNull()?.navigate({ to: "/website/command-center" });
  // Parity with navigateToCommandCenter's analytics tracking.
  track(ANALYTICS_EVENTS.COMMAND_CENTER_VIEWED);
}

export function navigateToSettings(
  category: SettingsCategory,
  options?: { replace?: boolean },
): void {
  void getRouterOrNull()?.navigate({
    to: "/settings/$category",
    params: { category },
    // Switching categories within settings should replace, not stack, so a
    // single history.back() (closeSettings) exits to the app rather than
    // walking back through every category that was visited.
    replace: options?.replace,
  });
}

export function isOnSettingsRoute(): boolean {
  return (
    getRouterOrNull()?.state.matches.some((m) =>
      m.routeId.startsWith("/settings"),
    ) ?? false
  );
}

export function goBackInHistory(): void {
  getRouterOrNull()?.history.back();
}

// False when the current entry is the first in the session history (index 0),
// e.g. after a quit+reopen restores a deep route directly. In that case
// `history.back()` is a no-op and callers should navigate to a fallback route.
export function canGoBackInHistory(): boolean {
  return getRouterOrNull()?.history.canGoBack() ?? false;
}

export function goForwardInHistory(): void {
  getRouterOrNull()?.history.forward();
}

// Accessors for code that needs to read router state outside of React (e.g.
// Zustand actions, imperative event handlers). Components should prefer the
// `useRouterState` hook from `@tanstack/react-router`.
export function getCurrentMatches() {
  return getRouterOrNull()?.state.matches ?? [];
}

export function getCurrentLocation() {
  return getRouterOrNull()?.state.location ?? null;
}

export function subscribeToRouterResolved(handler: () => void): () => void {
  const router = getRouterOrNull();
  if (!router) return () => {};
  return router.subscribe("onResolved", handler);
}
