import {
  ArrowSquareOut,
  CaretLeftIcon,
  CaretRightIcon,
} from "@phosphor-icons/react";
import { useHostTRPC, useHostTRPCClient } from "@posthog/host-router/react";
import { Button, ButtonGroup, cn } from "@posthog/quill";
import { BILLING_FLAG, PROJECT_BLUEBIRD_FLAG } from "@posthog/shared";
import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import { isContentlessTask } from "@posthog/shared/domain-types";
import { AnnouncementBanner } from "@posthog/ui/features/announcements/AnnouncementBanner";
import { AnnouncementsHost } from "@posthog/ui/features/announcements/AnnouncementsHost";
import { useServerArchiveSync } from "@posthog/ui/features/archive/useServerArchiveSync";
import { useAuthStateValue } from "@posthog/ui/features/auth/store";
import { UsageButton } from "@posthog/ui/features/billing/UsageButton";
import { UsageLimitModal } from "@posthog/ui/features/billing/UsageLimitModal";
import { useSpendGuardrails } from "@posthog/ui/features/billing/useSpendGuardrails";
import { BrowserTabStrip } from "@posthog/ui/features/browser-tabs/BrowserTabStrip";
import { BrowserTabsDndProvider } from "@posthog/ui/features/browser-tabs/BrowserTabsDnd";
import { TabShortcutFallback } from "@posthog/ui/features/browser-tabs/TabShortcutFallback";
import { isBluebirdOnlyPath } from "@posthog/ui/features/canvas/bluebirdRoutes";
import { ChannelHotkeys } from "@posthog/ui/features/canvas/components/ChannelHotkeys";
import { ChannelRouteSync } from "@posthog/ui/features/canvas/components/ChannelRouteSync";
import { ChannelsSidebar } from "@posthog/ui/features/canvas/components/ChannelsSidebar";
import {
  FeedbackModal,
  type FeedbackModalMode,
} from "@posthog/ui/features/canvas/components/FeedbackModal";
import { NavRail } from "@posthog/ui/features/canvas/components/NavRail";
import { useCanvasDeepLink } from "@posthog/ui/features/canvas/hooks/useCanvasDeepLink";
import { useChannelDeepLink } from "@posthog/ui/features/canvas/hooks/useChannelDeepLink";
import { useChannelsLayout } from "@posthog/ui/features/canvas/hooks/useChannelsLayout";
import { useChannelsWorld } from "@posthog/ui/features/canvas/hooks/useChannelsWorld";
import { useRailSurface } from "@posthog/ui/features/canvas/hooks/useRailSurface";
import { useShareLinkInterceptor } from "@posthog/ui/features/canvas/hooks/useShareLinkInterceptor";
import { useShellOwnsHeader } from "@posthog/ui/features/canvas/hooks/useShellOwnsHeader";
import { usePostHogWebFeedbackStore } from "@posthog/ui/features/canvas/stores/posthogWebFeedbackStore";
import { CommandMenu } from "@posthog/ui/features/command/CommandMenu";
import { GlobalFilePicker } from "@posthog/ui/features/command/GlobalFilePicker";
import { KeyboardShortcutsSheet } from "@posthog/ui/features/command/KeyboardShortcutsSheet";
import { ConnectivityBanner } from "@posthog/ui/features/connectivity/ConnectivityBanner";
import { useNewTaskDeepLink } from "@posthog/ui/features/deep-links/useNewTaskDeepLink";
import { useOpenTargetDeepLink } from "@posthog/ui/features/deep-links/useOpenTargetDeepLink";
import { useTaskDeepLink } from "@posthog/ui/features/deep-links/useTaskDeepLink";
import { useFeatureFlag } from "@posthog/ui/features/feature-flags/useFeatureFlag";
import { useInboxDeepLink } from "@posthog/ui/features/inbox/hooks/useInboxDeepLink";
import { useIntegrations } from "@posthog/ui/features/integrations/useIntegrations";
import { useLoopDeepLink } from "@posthog/ui/features/loops/hooks/useLoopDeepLink";
import { useScoutDeepLink } from "@posthog/ui/features/scouts/hooks/useScoutDeepLink";
import { useSetupDiscovery } from "@posthog/ui/features/setup/useSetupDiscovery";
import { NAV_RAIL_WIDTH } from "@posthog/ui/features/sidebar/constants";
import {
  beginSidebarPeek,
  cancelSidebarPeek,
  useSidebarPeekStore,
} from "@posthog/ui/features/sidebar/sidebarPeekStore";
import { useSidebarStore } from "@posthog/ui/features/sidebar/sidebarStore";
import { useSidebarData } from "@posthog/ui/features/sidebar/useSidebarData";
import { useVisualTaskOrder } from "@posthog/ui/features/sidebar/useVisualTaskOrder";
import { ExistingWorktreeDialog } from "@posthog/ui/features/task-detail/components/ExistingWorktreeDialog";
import { RemoteBranchCheckoutDialog } from "@posthog/ui/features/task-detail/components/RemoteBranchCheckoutDialog";
import { useTasks } from "@posthog/ui/features/tasks/useTasks";
import { TourOverlay } from "@posthog/ui/features/tour/components/TourOverlay";
import { UpdateAvailableModal } from "@posthog/ui/features/updates/UpdateAvailableModal";
import { WhatsNewModal } from "@posthog/ui/features/updates/WhatsNewModal";
import { useWorkspaces } from "@posthog/ui/features/workspace/useWorkspace";
import { AnimatedLogo } from "@posthog/ui/primitives/AnimatedLogo";
import { useAppView } from "@posthog/ui/router/useAppView";
import { openTask, openTaskInput } from "@posthog/ui/router/useOpenTask";
import { track } from "@posthog/ui/shell/analytics";
import { ContentHeader } from "@posthog/ui/shell/ContentHeader";
import { useCommandMenuStore } from "@posthog/ui/shell/commandMenuStore";
import { GlobalEventHandlers } from "@posthog/ui/shell/GlobalEventHandlers";
import { HedgehogMode } from "@posthog/ui/shell/HedgehogMode";
import { logger } from "@posthog/ui/shell/logger";
import { onFeatureFlagsLoaded } from "@posthog/ui/shell/posthogAnalyticsImpl";
import { SpaceSwitcher } from "@posthog/ui/shell/SpaceSwitcher";
import { useShortcutsSheetStore } from "@posthog/ui/shell/shortcutsSheetStore";
import { useHostCapabilities } from "@posthog/ui/shell/useHostCapabilities";
import { openUrlInBrowser } from "@posthog/ui/utils/browser";
import { isMac, isWindows } from "@posthog/ui/utils/platform";
import { getPostHogUrl } from "@posthog/ui/utils/urls";
import { Box, Flex } from "@radix-ui/themes";
import { useQueryClient } from "@tanstack/react-query";
import {
  createRootRoute,
  Outlet,
  useCanGoBack,
  useRouter,
  useRouterState,
} from "@tanstack/react-router";
import { SidebarClose, SidebarOpen } from "lucide-react";
import { useEffect, useRef, useState } from "react";

// The router devtools render their genuine floating overlay, mounted by the
// app's dev toolbar with the floating logo hidden so the toolbar owns the
// trigger — see RouterDevtools.

const log = logger.scope("root-route");

// On Windows the frameless window overlays the min/max/close controls on the
// top-right of the title bar (see window.ts titleBarOverlay). Reserve that strip
// so the tab strip / PostHog Web button never render under the native controls.
const WINDOWS_TITLEBAR_INSET = 140;

export const Route = createRootRoute({
  component: RootLayout,
});

function RootLayout() {
  const view = useAppView();
  const router = useRouter();
  const canGoBack = useCanGoBack();
  // Cloud-only hosts (web) run in a real browser tab that already provides
  // native back/forward chrome, so the in-app history buttons are redundant.
  const { localWorkspaces } = useHostCapabilities();
  // Forward availability isn't exposed by the router (and history.length counts
  // pre-app entries, so it can't be compared to __TSR_index). Track the newest
  // index we've reached: only a PUSH wipes the forward stack, so it resets the
  // newest to the current index. REPLACE mutates the current entry in place
  // (index unchanged, forward entries intact) and BACK/GO just move within the
  // existing stack, so both keep the max. Forward is live while below it.
  const historyIndex = useRouterState({
    select: (s) => s.location.state.__TSR_index,
  });
  const [newestIndex, setNewestIndex] = useState(historyIndex);
  useEffect(() => {
    return router.history.subscribe(({ location, action }) => {
      const idx = location.state.__TSR_index;
      setNewestIndex((prev) =>
        action.type === "PUSH" ? idx : Math.max(prev, idx),
      );
    });
  }, [router]);
  const canGoForward = historyIndex < newestIndex;

  // Feedback modal shown as an intercept before "PostHog Web" opens the web
  // app, routing once the modal is submitted or skipped.
  const [feedbackMode, setFeedbackMode] = useState<FeedbackModalMode | null>(
    null,
  );
  const currentProjectId = useAuthStateValue((s) => s.currentProjectId);

  // The user's current project on the correct cloud (region comes from
  // cloudRegion via getPostHogUrl), falling back to the account root. `null`
  // when the region is unknown — the "PostHog Web" button is disabled then, so
  // a click can never silently no-op.
  const posthogWebUrl = getPostHogUrl(
    currentProjectId ? `/project/${currentProjectId}` : "/",
  );

  const posthogWebFeedbackSeen = usePostHogWebFeedbackStore((s) => s.hasSeen);
  const posthogWebFeedbackHydrated = usePostHogWebFeedbackStore(
    (s) => s.hasHydrated,
  );
  const markPostHogWebFeedbackSeen = usePostHogWebFeedbackStore(
    (s) => s.markSeen,
  );

  // "PostHog Web" opens the feedback modal first and performs its navigation
  // only once the modal is submitted or skipped.
  const handleFeedbackFinished = () => {
    const finishedMode = feedbackMode;
    setFeedbackMode(null);
    if (finishedMode === "posthog-web" && posthogWebUrl) {
      markPostHogWebFeedbackSeen();
      void openUrlInBrowser(posthogWebUrl);
    }
  };

  const handleOpenPostHogWeb = () => {
    track(ANALYTICS_EVENTS.POSTHOG_WEB_OPENED);
    // Only skip the intercept once the persisted flag has hydrated, so a stale
    // pre-hydration default can't wrongly re-show it.
    if (posthogWebFeedbackHydrated && posthogWebFeedbackSeen && posthogWebUrl) {
      void openUrlInBrowser(posthogWebUrl);
      return;
    }
    setFeedbackMode("posthog-web");
  };
  const {
    isOpen: commandMenuOpen,
    setOpen: setCommandMenuOpen,
    toggle: toggleCommandMenu,
  } = useCommandMenuStore();
  const {
    isOpen: shortcutsSheetOpen,
    close: closeShortcutsSheet,
    toggle: toggleShortcutsSheet,
  } = useShortcutsSheetStore();
  const { data: tasks } = useTasks();
  const { data: workspaces, isFetched: workspacesFetched } = useWorkspaces();
  const trpc = useHostTRPC();
  const hostClient = useHostTRPCClient();
  const queryClient = useQueryClient();
  const reconcilingTaskIds = useRef<Set<string>>(new Set());
  const billingEnabled = useFeatureFlag(BILLING_FLAG);
  useSpendGuardrails();
  // "PostHog Web" is a channels-world affordance — show it only while the user
  // is actually seeing channels (toggle on, which itself requires the flag).
  const bluebirdEnabled = useFeatureFlag(
    PROJECT_BLUEBIRD_FLAG,
    import.meta.env.DEV,
  );
  const channelsWorld = useChannelsWorld();
  // The new channels layout has exactly one gate: its feature flag (no
  // sidebar toggle). When on it subsumes the channels alpha entirely.
  const channelsLayout = useChannelsLayout();
  const { hasSidebar } = useRailSurface();
  // When the sidebar is collapsed (Cmd+B) the title bar's left block shrinks to
  // fit its own controls so the tab strip flushes left with the content pane.
  const sidebarOpen = useSidebarStore((s) => s.open);
  // On screen, not merely un-collapsed: a destination with no list takes the
  // column away whatever the open flag says.
  const sidebarDocked = sidebarOpen && hasSidebar;
  // The corner belongs to whichever pane starts the framed inset.
  const framesOwnCorner = channelsLayout ? !sidebarDocked : sidebarDocked;

  const toggleSidebar = useSidebarStore((s) => s.toggle);
  const sidebarPeek = useSidebarPeekStore((s) => s.peek);
  // Toggling makes any hover-peek redundant (opening replaces the overlay;
  // closing must not leave it lingering under the pointer).
  const handleToggleSidebar = (): void => {
    cancelSidebarPeek();
    toggleSidebar();
  };

  const sidebarData = useSidebarData({ activeView: view });
  const visualTaskOrder = useVisualTaskOrder(sidebarData);
  const activeTaskId =
    view.type === "task-detail" && view.taskId ? view.taskId : null;

  useIntegrations();
  useTaskDeepLink();
  useOpenTargetDeepLink();
  useInboxDeepLink();
  useScoutDeepLink();
  useCanvasDeepLink();
  useChannelDeepLink();
  useLoopDeepLink();
  useShareLinkInterceptor();
  useSetupDiscovery();
  useNewTaskDeepLink();
  useServerArchiveSync();

  // hydrateTask is no longer needed — the URL is the source of truth and the
  // task cache populates the route automatically.

  useEffect(() => {
    if (!tasks || !workspaces || !workspacesFetched) return;
    const missing = tasks.filter(
      (t) =>
        t.latest_run?.environment === "cloud" &&
        !workspaces[t.id] &&
        !reconcilingTaskIds.current.has(t.id) &&
        !isContentlessTask(t),
    );
    if (missing.length === 0) return;
    const missingIds = missing.map((t) => t.id);
    for (const id of missingIds) reconcilingTaskIds.current.add(id);
    // Single batched IPC instead of one mutation per task — with many cloud
    // tasks the per-task pattern saturates the main thread at boot.
    hostClient.workspace.reconcileCloudWorkspaces
      .mutate({ taskIds: missingIds })
      .then((result) => {
        for (const id of missingIds) reconcilingTaskIds.current.delete(id);
        if (result.created.length > 0) {
          void queryClient.invalidateQueries({
            queryKey: trpc.workspace.getAll.queryKey(),
          });
        }
      })
      .catch((err) => {
        for (const id of missingIds) reconcilingTaskIds.current.delete(id);
        log.warn("Failed to reconcile cloud workspaces", err);
      });
  }, [tasks, workspaces, workspacesFetched, queryClient, hostClient, trpc]);

  // Flags resolve asynchronously — flag-gated routes below wait for this
  // before redirecting away from a restored route the user can't access.
  const [flagsLoaded, setFlagsLoaded] = useState(false);
  useEffect(() => onFeatureFlagsLoaded(() => setFlagsLoaded(true)), []);

  // Settings is a full-page route — drop the app chrome (header/sidebar/
  // space-switcher) so the panel occupies the full window.
  const isSettingsRoute = useRouterState({
    select: (s) => s.matches.some((m) => m.routeId.startsWith("/settings")),
  });

  // ShellLayout draws the in-pane header under `_shell`, so the shared
  // ContentHeader is mounted only where that layout isn't.
  const shellOwnsHeader = useShellOwnsHeader();

  // The bluebird routes stay registered regardless of the flag, so a stale URL,
  // a restored session, or a persisted browser tab could strand a flag-off user
  // on chrome they have no way back out of. Once flags resolve, send them back
  // to a new task.
  const onBluebirdOnlyPath = useRouterState({
    select: (s) => isBluebirdOnlyPath(s.location.pathname),
  });
  useEffect(() => {
    if (flagsLoaded && !bluebirdEnabled && onBluebirdOnlyPath) {
      openTaskInput();
    }
  }, [flagsLoaded, bluebirdEnabled, onBluebirdOnlyPath]);

  if (isSettingsRoute) {
    return (
      <Flex direction="column" height="100%">
        <ConnectivityBanner />
        <AnnouncementBanner />
        <Outlet />
        <CommandMenu open={commandMenuOpen} onOpenChange={setCommandMenuOpen} />
        <GlobalFilePicker />
        <KeyboardShortcutsSheet
          open={shortcutsSheetOpen}
          onOpenChange={(open) => (open ? null : closeShortcutsSheet())}
        />
        <GlobalEventHandlers
          allTasks={tasks ?? []}
          onToggleCommandMenu={toggleCommandMenu}
          onToggleShortcutsSheet={toggleShortcutsSheet}
          visualTaskOrder={visualTaskOrder}
        />
        {/* The settings shell has never mounted the tab strip, so nothing here
            was stopping Cmd+W from closing the window. */}
        <TabShortcutFallback enabled />
        {billingEnabled && <UsageLimitModal />}
        <AnnouncementsHost />
        <UpdateAvailableModal />
        <WhatsNewModal />
        <RemoteBranchCheckoutDialog />
        <ExistingWorktreeDialog />
      </Flex>
    );
  }

  return (
    // DnD scope for the tab strip's drag-to-reorder (pill sortables live in
    // the title bar; the provider must sit above them).
    <BrowserTabsDndProvider>
      <Flex direction="column" height="100%" className="bg-chrome">
        {/* Full-width title bar: a window-drag region carrying the PostHog
            mark. The left section sizes to its controls so the tab strip sits
            beside the history buttons; its padding clears the macOS stoplights
            via env(titlebar-area-x), the system-reported right edge of the
            traffic-light strip (see titleBarOverlay in window.ts). */}
        <Flex
          align="center"
          className="drag h-10 shrink-0"
          style={{
            paddingRight: isWindows ? WINDOWS_TITLEBAR_INSET : undefined,
          }}
        >
          <Flex
            id="title-bar-left"
            align="center"
            justify="start"
            gap="3"
            className="shrink-0 pr-2"
            style={{
              // Traffic-light size varies by macOS version, so a fixed inset
              // over- or under-shoots; the env var fallback covers hosts
              // without Window Controls Overlay.
              paddingLeft: isMac ? "env(titlebar-area-x, 78px)" : "78px",
            }}
          >
            <Flex align="center" gap="2" className="no-drag">
              <AnimatedLogo size={26} animate="hover" />
              <Button
                size="icon-sm"
                aria-label="Toggle sidebar"
                onClick={handleToggleSidebar}
                onMouseEnter={() => {
                  if (!sidebarOpen) beginSidebarPeek();
                }}
              >
                {sidebarOpen ? (
                  <SidebarClose size={10} className="text-muted-foreground" />
                ) : (
                  <SidebarOpen size={10} className="text-muted-foreground" />
                )}
              </Button>
            </Flex>
            {localWorkspaces && (
              <ButtonGroup className="no-drag">
                <Button
                  variant="outline"
                  size="icon-sm"
                  aria-label="Back"
                  disabled={!canGoBack}
                  onClick={() => router.history.back()}
                >
                  <CaretLeftIcon size={14} />
                </Button>
                <Button
                  variant="outline"
                  size="icon-sm"
                  aria-label="Forward"
                  disabled={!canGoForward}
                  onClick={() => router.history.forward()}
                >
                  <CaretRightIcon size={14} />
                </Button>
              </ButtonGroup>
            )}
          </Flex>
          {/* The strip owns the title bar's middle in both layouts. Search
              moved to the rail to make room for it (see NavRail). The strip is
              also the only global owner of Cmd+W, so the fallback has to hold
              that key wherever the strip isn't mounted. */}
          <BrowserTabStrip />
          {/* Gated so an empty right-side group can't claim a no-drag rect
              in the title bar for nothing — every pixel without controls
              should drag the window. */}
          {(billingEnabled || channelsWorld) && (
            <Flex align="center" gap="2" className="no-drag ml-auto pr-3">
              <UsageButton />
              {channelsWorld && (
                <Button
                  variant="outline"
                  size="sm"
                  disabled={!posthogWebUrl}
                  onClick={handleOpenPostHogWeb}
                >
                  <ArrowSquareOut size={14} />
                  PostHog Web
                </Button>
              )}
            </Flex>
          )}
        </Flex>
        <ConnectivityBanner />
        <Flex flexGrow="1" overflow="hidden" className="relative">
          {/* Scrim under the peeked nav: dims the content while the overlay is
              out. Purely visual (pointer-transparent) and paired with the
              panel's slide — same 200ms ease-out — so they read as one unit. */}
          {!sidebarOpen && (
            <Box
              aria-hidden
              style={{ left: channelsLayout ? NAV_RAIL_WIDTH : 0 }}
              // The radix preset replaces Tailwind's palette, so plain
              // `bg-black/*` doesn't exist — use the radix black-alpha scale
              // (--black-a2 = 10%, --black-a5 = 30%).
              className={`pointer-events-none absolute inset-0 z-40 bg-blackA-2 transition-opacity duration-200 ease-out motion-reduce:transition-none dark:bg-blackA-5 ${
                sidebarPeek ? "opacity-100" : "opacity-0"
              }`}
            />
          )}
          {/* Outside the sidebar on purpose: collapsing the sidebar (Cmd+B)
              must not take the destinations with it. */}
          {channelsLayout && <NavRail />}
          {hasSidebar && <ChannelsSidebar />}
          {/* Content sits in a bordered, rounded card inset from the window
              edges — the framed pane from the design. The rounded corner
              belongs to whichever pane starts the inset: the sidebar when it
              is docked, this pane when it isn't and the rail holds the edge.
              Without a rail there is nothing to inset from until the sidebar
              opens, which is the corner this pane kept before. */}
          <Box flexGrow="1" className="overflow-hidden">
            <Box
              className={cn(
                "h-full overflow-hidden border-border border-t bg-background",
                // A docked sidebar already draws this edge; two owners stack
                // two 1px lines into one seam.
                !sidebarDocked && "border-l",
                framesOwnCorner && "rounded-tl-sm",
              )}
            >
              <Flex direction="column" height="100%">
                {/* Inside the framed pane, not the app column: announcements
                    overlay the content, never the sidebar. */}
                <AnnouncementBanner />
                {/* The shell renders its own header (ShellLayout);
                      everywhere else the shared header carries the view title
                      and, on a task, its action row. */}
                {!shellOwnsHeader && <ContentHeader />}
                <Box flexGrow="1" overflow="hidden">
                  <Outlet />
                </Box>
              </Flex>
            </Box>
          </Box>
        </Flex>
        <CommandMenu open={commandMenuOpen} onOpenChange={setCommandMenuOpen} />
        <GlobalFilePicker />
        <KeyboardShortcutsSheet
          open={shortcutsSheetOpen}
          onOpenChange={(open) => (open ? null : closeShortcutsSheet())}
        />
        <GlobalEventHandlers
          allTasks={tasks ?? []}
          onToggleCommandMenu={toggleCommandMenu}
          onToggleShortcutsSheet={toggleShortcutsSheet}
          visualTaskOrder={visualTaskOrder}
        />
        {/* Renders nothing — owns ⌘1-9 under the channels layout. Mounted here
            rather than in the switcher, which only exists once a channel is
            already scoped. */}
        <ChannelHotkeys />
        {/* Renders nothing — owns which space is scoped. The sidebar used to,
            but the rail can take that column away and the scoping still has to
            happen. */}
        <ChannelRouteSync />
        {/* Renders nothing — wires the ⌥↑/⌥↓ task-cycling shortcuts. */}
        <SpaceSwitcher
          tasks={visualTaskOrder}
          activeTaskId={activeTaskId}
          allTasks={tasks ?? []}
          isOnNewTask={
            view.type === "task-input" || view.type === "task-pending"
          }
          onNavigateToTask={openTask}
          onNewTask={openTaskInput}
        />
        <TourOverlay />
        {billingEnabled && <UsageLimitModal />}
        <AnnouncementsHost />
        <UpdateAvailableModal />
        <WhatsNewModal />
        <RemoteBranchCheckoutDialog />
        <FeedbackModal
          mode={feedbackMode}
          onFinished={handleFeedbackFinished}
        />
        <ExistingWorktreeDialog />
        <HedgehogMode />
      </Flex>
    </BrowserTabsDndProvider>
  );
}
