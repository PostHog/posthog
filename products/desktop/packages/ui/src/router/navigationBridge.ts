import type { NotificationTarget } from "@posthog/platform/notifications";
import type { SettingsCategory } from "@posthog/ui/features/settings/types";
import {
  navigationSourceHref,
  reportNavigationState,
  settingsSourceHref,
  sourceHrefFromSearch,
} from "./reportNavigation";
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

// A plain navigation never changes which tab you are in; the tab strip
// re-stamps the new history entry with the active tab after the fact (see
// decideTabNavigation). The new-task screens key their composer session on
// `state.tabId` (getTaskInputSessionId) and remount on that key, so an entry
// born unstamped flips the key mid-mount and the remounted composer finds the
// one-shot prefill already consumed — silently dropping prompts handed to
// openTaskInput (posthog-code://new?prompt= deep links, show_actions compose
// buttons). Carrying the tag forward matches what the strip would stamp, so
// the session key never changes under the composer. Only the tag: the other
// state keys (loopListOrigin, inboxBackOrigin) describe the route being left.
const keepTabTag = (prev: { tabId?: string }): { tabId?: string } => ({
  tabId: prev.tabId,
});

export function navigateToNewTask(): void {
  void getRouterOrNull()?.navigate({ to: "/new", state: keepTabTag });
}

export function navigateToTaskDetail(taskId: string): void {
  void getRouterOrNull()?.navigate({
    to: "/tasks/$taskId",
    params: { taskId },
  });
}

export function navigateToPullRequestView(prUrl: string): void {
  void getRouterOrNull()?.navigate({
    to: "/pr",
    search: { prUrl },
  });
}

export function navigateToActivity(): void {
  void getRouterOrNull()?.navigate({ to: "/activity" });
}

export function navigateToCanvases(canvasId?: string): void {
  void getRouterOrNull()?.navigate({
    to: "/canvases",
    search: { canvas: canvasId },
  });
}

export function navigateToHome(): void {
  void getRouterOrNull()?.navigate({ to: "/" });
}

export function navigateToFeed(feedId: string): void {
  void getRouterOrNull()?.navigate({
    to: "/feeds/$feedId",
    params: { feedId },
  });
}

export function navigateToFeeds(): void {
  void getRouterOrNull()?.navigate({ to: "/feeds" });
}

export function navigateToChannel(channelId: string): void {
  void getRouterOrNull()?.navigate({
    to: "/spaces/$channelId",
    params: { channelId },
  });
}

export function navigateToChannelTask(channelId: string, taskId: string): void {
  void getRouterOrNull()?.navigate({
    to: "/spaces/$channelId/tasks/$taskId",
    params: { channelId, taskId },
  });
}

export function navigateToChannelNewTask(channelId: string): void {
  void getRouterOrNull()?.navigate({
    to: "/spaces/$channelId/new",
    params: { channelId },
    state: keepTabTag,
  });
}

export function navigateToChannelDashboard(
  channelId: string,
  dashboardId: string,
): void {
  void getRouterOrNull()?.navigate({
    to: "/spaces/$channelId/dashboards/$dashboardId",
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
// to a channel resolves to /spaces/$channelId/tasks/$taskId; direct
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
  // Channel context is unavailable here, so a channel task opens unscoped —
  // acceptable for this rare gap; the registered handler covers the live app.
  if (target.kind === "task") {
    navigateToTaskDetail(target.taskId);
  } else {
    navigateToChannelDashboard(target.channelId, target.dashboardId);
  }
}

export function navigateToInbox(): void {
  void getRouterOrNull()?.navigate({ to: "/inbox" });
}

export function navigateToInboxReports(): void {
  void getRouterOrNull()?.navigate({ to: "/inbox/reports" });
}

export function navigateToReport(
  reportId: string,
  options?: { preserveSource?: boolean; returnToTriage?: boolean },
): void {
  const router = getRouterOrNull();
  if (!router) return;
  if (options?.returnToTriage) {
    const location = router.history.location;
    router.history.replace(location.href, {
      ...location.state,
      inboxTriageOrigin: { reportId },
    });
  }
  const from =
    options?.preserveSource === false ? undefined : navigationSourceHref();
  void router.navigate({
    to: "/reports/$reportId",
    params: { reportId },
    search: from ? { from } : {},
    state: reportNavigationState,
  });
}

export function navigateToInboxPullRequestDetail(reportId: string): void {
  navigateToReport(reportId);
}

export function navigateToInboxReportDetail(
  reportId: string,
  options?: { returnToTriage?: boolean },
): void {
  navigateToReport(reportId, options);
}

export function navigateToInboxDismissedDetail(reportId: string): void {
  navigateToReport(reportId);
}

export function navigateToChannelReportDetail(
  _channelId: string,
  reportId: string,
): void {
  navigateToReport(reportId);
}

export function navigateToLoops(options?: { ignoreBlocker?: boolean }): void {
  void getRouterOrNull()?.navigate({
    to: "/loops",
    ignoreBlocker: options?.ignoreBlocker,
  });
}

export function navigateToNewLoop(): void {
  void getRouterOrNull()?.navigate({ to: "/loops/new" });
}

export function navigateToLoopDetail(
  loopId: string,
  options?: { ignoreBlocker?: boolean; edit?: boolean },
): void {
  void getRouterOrNull()?.navigate({
    to: "/loops/$loopId",
    params: { loopId },
    search: options?.edit ? { edit: true } : {},
    ignoreBlocker: options?.ignoreBlocker,
  });
}

export function navigateToArchived(): void {
  void getRouterOrNull()?.navigate({ to: "/archived" });
}

export function navigateToCommandCenter(): void {
  void getRouterOrNull()?.navigate({ to: "/command-center" });
}

export function navigateToContext(path?: string): void {
  void getRouterOrNull()?.navigate({
    to: "/context",
    search: { path },
  });
}

// The spaces index, where the project's spaces are listed.
export function navigateToSpaces(): void {
  void getRouterOrNull()?.navigate({ to: "/spaces" });
}

export function navigateToSpacesContext(path?: string): void {
  void getRouterOrNull()?.navigate({
    to: "/spaces/context",
    search: { path },
  });
}

export function navigateToSettings(
  category: SettingsCategory,
  options?: { replace?: boolean },
): void {
  const from = settingsSourceHref();
  void getRouterOrNull()?.navigate({
    to: "/settings/$category",
    params: { category },
    search: from ? { from } : {},
    replace: options?.replace,
  });
}

// Settings sits under the pathless `_shell` layout, so its route IDs read
// `/_shell/settings/…` rather than `/settings/…`. Match on the substring so a
// later move between layouts does not silently switch this off.
export function isSettingsRouteId(routeId: string): boolean {
  return routeId.includes("/settings/");
}

export function isOnSettingsRoute(): boolean {
  return (
    getRouterOrNull()?.state.matches.some((m) =>
      isSettingsRouteId(m.routeId),
    ) ?? false
  );
}

export function leaveSettingsRoute(): void {
  const router = getRouterOrNull();
  if (!router) return;
  const from = sourceHrefFromSearch(router.state.location);
  if (!from) {
    void router.navigate({ to: "/new", state: keepTabTag });
    return;
  }
  router.history.push(from, { tabId: router.history.location.state.tabId });
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

export function subscribeToRouterResolved(handler: () => void): () => void {
  const router = getRouterOrNull();
  if (!router) return () => {};
  return router.subscribe("onResolved", handler);
}
