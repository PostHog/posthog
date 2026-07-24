import { LOOPS_FLAG, PROJECT_BLUEBIRD_FLAG } from "@posthog/shared";
import {
  ANALYTICS_EVENTS,
  type SidebarNavItem,
} from "@posthog/shared/analytics-events";
import { useCommandCenterStore } from "@posthog/ui/features/command-center/commandCenterStore";
import { useFeatureFlag } from "@posthog/ui/features/feature-flags/useFeatureFlag";
import { useInboxAllReports } from "@posthog/ui/features/inbox/hooks/useInboxAllReports";
import { openSettings } from "@posthog/ui/features/settings/hooks/useOpenSettings";
import {
  CUSTOMIZABLE_NAV_ITEM_IDS,
  type CustomizableNavItemId,
  isNavItemVisible,
  orderedNavItems,
} from "@posthog/ui/features/sidebar/constants";
import { useSidebarStore } from "@posthog/ui/features/sidebar/sidebarStore";
import { useTasks } from "@posthog/ui/features/tasks/useTasks";
import {
  navigateToActivity,
  navigateToCommandCenter,
  navigateToInbox,
  navigateToLoops,
  navigateToWebsiteCommandCenter,
} from "@posthog/ui/router/navigationBridge";
import { useAppView } from "@posthog/ui/router/useAppView";
import { openTaskInput } from "@posthog/ui/router/useOpenTask";
import { track } from "@posthog/ui/shell/analytics";
import { useCommandMenuStore } from "@posthog/ui/shell/commandMenuStore";
import { Box, Flex } from "@radix-ui/themes";
import { useRouterState } from "@tanstack/react-router";
import type { ReactNode } from "react";
import { ActivityItem } from "./items/ActivityItem";
import { CommandCenterItem } from "./items/CommandCenterItem";
import { ConfigureItem } from "./items/ConfigureItem";
import { ContextsItem } from "./items/ContextsItem";
import { InboxItem } from "./items/InboxItem";
import { LoopsItem } from "./items/LoopsItem";
import { NewTaskItem } from "./items/NewTaskItem";
import { SearchItem } from "./items/SearchItem";

const SIDEBAR_INBOX_REFETCH_INTERVAL_MS = 60_000;

interface SidebarNavSectionProps {
  // The Command Center badge counts how many command-center cells point at a
  // live task. Deriving it needs the task list, which the Code pane's
  // SidebarMenu already subscribes to — so it passes the count down here to
  // avoid a second live useTasks subscription. The Channels pane renders this
  // standalone with no count, so the component derives its own (below).
  commandCenterActiveCount?: number;
}

// The sidebar navigation section shared by the Code pane (above the task list)
// and the Channels pane. It is fully self-contained — every item's active
// state, badge count, and click handler is wired here — so it can be dropped
// into either layout. In the Channels space, destinations with a /website
// mirror (Command Center) stay in that space; Inbox and New task have
// no mirror yet and jump back to Code.
// Configure opens the shared settings UI. Search opens the command menu in
// place and defaults to the collapsible More row; the Customize sidebar
// dialog controls which items show at the top level.
export function SidebarNavSection({
  commandCenterActiveCount: providedActiveCount,
}: SidebarNavSectionProps = {}) {
  const view = useAppView();
  // Loops stays behind the loops flag; default on in dev so local builds
  // keep the nav item. Also gates the per-channel Loops tab (see ChannelTabs).
  const loopsEnabled = useFeatureFlag(LOOPS_FLAG, import.meta.env.DEV);
  // Channels stay behind project-bluebird: the "Enable channels" nav row (and
  // the Canvas row it reveals) only appear where the canvas backend is wired.
  const bluebirdEnabled = useFeatureFlag(
    PROJECT_BLUEBIRD_FLAG,
    import.meta.env.DEV,
  );
  const channelsEnabled =
    useSidebarStore((s) => s.channelsEnabled) && bluebirdEnabled;
  const setChannelsEnabled = useSidebarStore((s) => s.setChannelsEnabled);

  // When this section renders inside the Channels space, the destinations that
  // have a /website mirror stay in that space; everything else (and the whole
  // section in the Code space) uses the canonical routes. Inbox and New task
  // have no mirror yet, so they intentionally jump back to Code.
  const inChannels = useRouterState({
    select: (s) => s.location.pathname.startsWith("/website"),
  });
  const goNewTask = () =>
    openTaskInput(inChannels ? { space: "website" } : undefined);
  const goCommandCenter = inChannels
    ? navigateToWebsiteCommandCenter
    : navigateToCommandCenter;

  // Active flags are pure functions of the current view — mirror what
  // useSidebarData derives, without pulling in its task-loading.
  const isHomeActive =
    view.type === "task-input" || view.type === "task-pending";
  const isActivityActive = view.type === "activity";
  const isInboxActive = view.type === "inbox";
  const isLoopsActive = view.type === "loops";
  const isCommandCenterActive = view.type === "command-center";

  // Open pull requests in the inbox — the main CTA, and the same count the inbox
  // Pull requests tab shows, so the badge and the tab always agree.
  // `ignoreFilters` keeps the badge stable against the inbox's filter chrome;
  // scope still follows the user's For-you / project choice.
  // The sidebar mounts on every route, so its badge polls slowly; opening the
  // inbox adds its own 3s observers and React Query uses the shortest interval.
  const { counts: inboxCounts } = useInboxAllReports({
    ignoreFilters: true,
    refetchIntervalMs: SIDEBAR_INBOX_REFETCH_INTERVAL_MS,
  });
  const inboxPullRequestCount = inboxCounts.pulls;

  // Only subscribe to the task list when a parent hasn't already supplied the
  // count — keeps the standalone (Channels) render self-contained without
  // opening a redundant subscription when composed inside SidebarMenu.
  const needsOwnCount = providedActiveCount === undefined;
  const showAllUsers = useSidebarStore((s) => s.showAllUsers);
  const showInternal = useSidebarStore((s) => s.showInternal);
  const { data: allTasks = [] } = useTasks(
    { showAllUsers, showInternal },
    { enabled: needsOwnCount },
  );
  const commandCenterCells = useCommandCenterStore((s) => s.cells);
  const ownActiveCount = (() => {
    const taskIds = new Set(allTasks.map((t) => t.id));
    return commandCenterCells.filter(
      (taskId) => taskId != null && taskIds.has(taskId),
    ).length;
  })();
  const commandCenterActiveCount = providedActiveCount ?? ownActiveCount;

  const openCommandMenu = useCommandMenuStore((s) => s.open);

  // depth 1 means the row was clicked inside the expanded More section.
  const withNavTrack =
    (item: SidebarNavItem, action: () => void, depth: 0 | 1 = 0) =>
    () => {
      track(ANALYTICS_EVENTS.SIDEBAR_NAV_ITEM_CLICKED, {
        item,
        in_more: depth === 1,
      });
      action();
    };

  const navItemOverrides = useSidebarStore((s) => s.navItemOverrides);
  const navItemOrder = useSidebarStore((s) => s.navItemOrder);
  const orderedItems = orderedNavItems(navItemOrder);
  const hidden = new Set<CustomizableNavItemId>(
    CUSTOMIZABLE_NAV_ITEM_IDS.filter(
      (id) => !isNavItemVisible(navItemOverrides, id),
    ),
  );
  const navItemAvailable: Record<CustomizableNavItemId, boolean> = {
    inbox: true,
    "command-center": true,
    contexts: bluebirdEnabled,
    // Activity (the mentions feed) is a channels surface, so it only appears
    // once channels are enabled.
    activity: channelsEnabled,
    configure: true,
    loops: loopsEnabled,
  };

  const handleChannelsToggle = (depth: 0 | 1) => (checked: boolean) => {
    setChannelsEnabled(checked);
    track(ANALYTICS_EVENTS.SIDEBAR_NAV_ITEM_CLICKED, {
      item: "contexts",
      in_more: depth === 1,
    });
    track(ANALYTICS_EVENTS.CHANNEL_ACTION, {
      action_type: "toggle_channels",
      surface: "nav",
    });
    // This toggle replaced the old Code/Channels space boundary; keep firing
    // the legacy enter/leave events so space-adoption dashboards stay continuous.
    track(ANALYTICS_EVENTS.CHANNEL_ACTION, {
      action_type: checked ? "enter_space" : "leave_space",
      surface: "nav",
    });
  };

  // One renderer per customizable item, used for both the top level (depth 0)
  // and the expanded More section (depth 1) so the two never drift apart.
  const renderNavItem: Record<
    CustomizableNavItemId,
    (depth: 0 | 1) => ReactNode
  > = {
    inbox: (depth) => (
      <InboxItem
        depth={depth}
        isActive={isInboxActive}
        onClick={withNavTrack("inbox", navigateToInbox, depth)}
        pullRequestCount={inboxPullRequestCount}
      />
    ),
    "command-center": (depth) => (
      <CommandCenterItem
        depth={depth}
        isActive={isCommandCenterActive}
        onClick={withNavTrack("command_center", goCommandCenter, depth)}
        activeCount={commandCenterActiveCount}
      />
    ),
    contexts: (depth) => (
      <ContextsItem
        depth={depth}
        checked={channelsEnabled}
        onCheckedChange={handleChannelsToggle(depth)}
      />
    ),
    activity: (depth) => (
      <ActivityItem
        depth={depth}
        isActive={isActivityActive}
        onClick={withNavTrack("activity", navigateToActivity, depth)}
      />
    ),
    configure: (depth) => (
      <ConfigureItem
        depth={depth}
        onClick={withNavTrack("configure", () => openSettings("agents"), depth)}
      />
    ),
    loops: (depth) => (
      <LoopsItem
        depth={depth}
        isActive={isLoopsActive}
        onClick={withNavTrack("loops", navigateToLoops, depth)}
      />
    ),
  };

  const topLevelItems = orderedItems.filter(
    ({ id }) => navItemAvailable[id] && !hidden.has(id),
  );
  return (
    <Flex direction="column" className="shrink-0 gap-px px-2 py-2">
      <Box mb="2">
        <NewTaskItem
          isActive={isHomeActive}
          onClick={withNavTrack("new_task", goNewTask)}
        />
      </Box>

      <Box>
        <SearchItem onClick={withNavTrack("search", openCommandMenu)} />
      </Box>

      {topLevelItems.map(({ id }) => (
        <Box key={id}>{renderNavItem[id](0)}</Box>
      ))}
    </Flex>
  );
}
