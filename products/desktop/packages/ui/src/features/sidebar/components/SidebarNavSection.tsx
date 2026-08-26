import { LOOPS_FLAG, PROJECT_BLUEBIRD_FLAG } from "@posthog/shared";
import {
  ANALYTICS_EVENTS,
  type SidebarNavItem,
} from "@posthog/shared/analytics-events";
import { useOpenBrowserTab } from "@posthog/ui/features/browser-tabs/useOpenBrowserTab";
import { useCommandCenterActiveCount } from "@posthog/ui/features/command-center/useCommandCenterActiveCount";
import { useChannelReportsEnabled } from "@posthog/ui/features/feature-flags/useChannelReportsEnabled";
import { useContextLayerFlag } from "@posthog/ui/features/feature-flags/useContextLayerFlag";
import { useFeatureFlag } from "@posthog/ui/features/feature-flags/useFeatureFlag";
import { useReportsInboxEnabled } from "@posthog/ui/features/feature-flags/useReportsInboxEnabled";
import { useInboxDecisionCount } from "@posthog/ui/features/inbox/hooks/useInboxDecisionCount";
import { openSettings } from "@posthog/ui/features/settings/hooks/useOpenSettings";
import {
  CUSTOMIZABLE_NAV_ITEM_IDS,
  type CustomizableNavItemId,
  isNavItemVisible,
  orderedNavItems,
} from "@posthog/ui/features/sidebar/constants";
import { useSidebarStore } from "@posthog/ui/features/sidebar/sidebarStore";
import {
  navigateToActivity,
  navigateToCommandCenter,
  navigateToContext,
  navigateToInbox,
  navigateToLoops,
  navigateToSpacesContext,
} from "@posthog/ui/router/navigationBridge";
import { useAppView } from "@posthog/ui/router/useAppView";
import { openTaskInput } from "@posthog/ui/router/useOpenTask";
import { track } from "@posthog/ui/shell/analytics";
import { useCommandMenuStore } from "@posthog/ui/shell/commandMenuStore";
import { Box, Flex } from "@radix-ui/themes";
import { useRouterState } from "@tanstack/react-router";
import type { MouseEventHandler, ReactNode } from "react";
import { ActivityItem } from "./items/ActivityItem";
import { CommandCenterItem } from "./items/CommandCenterItem";
import { ConfigureItem } from "./items/ConfigureItem";
import { ContextItem } from "./items/ContextItem";
import { InboxItem } from "./items/InboxItem";
import { LoopsItem } from "./items/LoopsItem";
import { NewTaskItem } from "./items/NewTaskItem";
import { SearchItem } from "./items/SearchItem";

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
  const openBrowserTab = useOpenBrowserTab();
  // Loops stays behind the loops flag; default on in dev so local builds
  // keep the nav item. Also gates the per-channel Loops tab (see ChannelTabs).
  const loopsEnabled = useFeatureFlag(LOOPS_FLAG, import.meta.env.DEV);
  // Channels stay behind project-bluebird, including channel-only nav items.
  const bluebirdEnabled = useFeatureFlag(
    PROJECT_BLUEBIRD_FLAG,
    import.meta.env.DEV,
  );
  // With channel reports on, spaces own reports (sidebar tab + feed) and the
  // inbox disappears as a destination.
  const channelReportsEnabled = useChannelReportsEnabled();
  const reportsInboxEnabled = useReportsInboxEnabled();
  const inboxDecisionCount = useInboxDecisionCount();
  const contextEnabled = useContextLayerFlag();
  const inSpaces = useRouterState({
    select: (state) => state.location.pathname.startsWith("/spaces"),
  });
  const goContext = inSpaces ? navigateToSpacesContext : navigateToContext;
  const goNewTask = () => openTaskInput();

  // Active flags are pure functions of the current view — mirror what
  // useSidebarData derives, without pulling in its task-loading.
  const isHomeActive =
    view.type === "task-input" || view.type === "task-pending";
  const isActivityActive = view.type === "activity";
  const isInboxActive = view.type === "inbox";
  const isLoopsActive = view.type === "loops";
  const isCommandCenterActive = view.type === "command-center";
  const isContextActive = view.type === "context";

  // Only subscribe to the task list when a parent hasn't already supplied the
  // count — keeps the standalone (Channels) render self-contained without
  // opening a redundant subscription when composed inside SidebarMenu.
  const needsOwnCount = providedActiveCount === undefined;
  const ownActiveCount = useCommandCenterActiveCount({
    enabled: needsOwnCount,
  });
  const commandCenterActiveCount = providedActiveCount ?? ownActiveCount;

  const openCommandMenu = useCommandMenuStore((s) => s.open);

  // depth 1 means the row was clicked inside the expanded More section.
  const withNavTrack =
    (
      item: SidebarNavItem,
      action: () => void,
      depth: 0 | 1 = 0,
      newTab?: { href: string; prepare?: () => void },
    ): MouseEventHandler<Element> =>
    (event) => {
      track(ANALYTICS_EVENTS.SIDEBAR_NAV_ITEM_CLICKED, {
        item,
        in_more: depth === 1,
        layout: "code",
      });
      if (newTab && (event.metaKey || event.ctrlKey)) {
        event.preventDefault();
        newTab.prepare?.();
        openBrowserTab(newTab.href);
        return;
      }
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
    // The global reports inbox reclaims the slot from the channel-reports
    // takeover; without it, spaces own reports and the entry goes away.
    inbox: !channelReportsEnabled || reportsInboxEnabled,
    "command-center": true,
    contexts: contextEnabled,
    activity: bluebirdEnabled,
    configure: true,
    loops: loopsEnabled,
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
        onClick={withNavTrack("inbox", navigateToInbox, depth, {
          href: "/inbox",
        })}
        decisionCount={inboxDecisionCount}
      />
    ),
    "command-center": (depth) => (
      <CommandCenterItem
        depth={depth}
        isActive={isCommandCenterActive}
        onClick={withNavTrack(
          "command_center",
          navigateToCommandCenter,
          depth,
          { href: "/command-center" },
        )}
        activeCount={commandCenterActiveCount}
      />
    ),
    activity: (depth) => (
      <ActivityItem
        depth={depth}
        isActive={isActivityActive}
        onClick={withNavTrack("activity", navigateToActivity, depth, {
          href: "/activity",
        })}
      />
    ),
    configure: (depth) => (
      <ConfigureItem
        depth={depth}
        onClick={withNavTrack("configure", () => openSettings(), depth)}
      />
    ),
    loops: (depth) => (
      <LoopsItem
        depth={depth}
        isActive={isLoopsActive}
        onClick={withNavTrack("loops", navigateToLoops, depth, {
          href: "/loops",
        })}
      />
    ),
    contexts: (depth) => (
      <ContextItem
        depth={depth}
        isActive={isContextActive}
        onClick={withNavTrack("contexts", goContext, depth)}
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
          onClick={withNavTrack("new_task", goNewTask, 0, { href: "/new" })}
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
