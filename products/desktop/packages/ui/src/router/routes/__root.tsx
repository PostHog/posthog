import {
  ArrowSquareOut,
  CaretLeftIcon,
  CaretRightIcon,
} from "@phosphor-icons/react";
import { useHostTRPC, useHostTRPCClient } from "@posthog/host-router/react";
import { Button, ButtonGroup } from "@posthog/quill";
import {
  BILLING_FLAG,
  PROJECT_BLUEBIRD_FLAG,
  SYNC_CLOUD_TASKS_FLAG,
} from "@posthog/shared";
import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import { isContentlessTask } from "@posthog/shared/domain-types";
import { DeepLinkApprovalModal } from "@posthog/ui/features/agent-applications/components/DeepLinkApprovalModal";
import { useApprovalDeepLink } from "@posthog/ui/features/agent-applications/hooks/useApprovalDeepLink";
import { useAuthStateValue } from "@posthog/ui/features/auth/store";
import { UsageBillingAnnouncementModal } from "@posthog/ui/features/billing/UsageBillingAnnouncementModal";
import { UsageButton } from "@posthog/ui/features/billing/UsageButton";
import { UsageLimitModal } from "@posthog/ui/features/billing/UsageLimitModal";
import { BlankTabView } from "@posthog/ui/features/browser-tabs/BlankTabView";
import { BrowserTabStrip } from "@posthog/ui/features/browser-tabs/BrowserTabStrip";
import { BrowserTabsDndProvider } from "@posthog/ui/features/browser-tabs/BrowserTabsDnd";
import { useActiveTabIsBlank } from "@posthog/ui/features/browser-tabs/useBrowserTabs";
import { ChannelsSidebar } from "@posthog/ui/features/canvas/components/ChannelsSidebar";
import { useChannelsSidebarStore } from "@posthog/ui/features/canvas/components/channelsSidebarStore";
import {
  FeedbackModal,
  type FeedbackModalMode,
} from "@posthog/ui/features/canvas/components/FeedbackModal";
import { useCanvasDeepLink } from "@posthog/ui/features/canvas/hooks/useCanvasDeepLink";
import { useChannelDeepLink } from "@posthog/ui/features/canvas/hooks/useChannelDeepLink";
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
import { useScoutDeepLink } from "@posthog/ui/features/scouts/hooks/useScoutDeepLink";
import { useSetupDiscovery } from "@posthog/ui/features/setup/useSetupDiscovery";
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
import LogosLandscape from "@posthog/ui/primitives/Logo";
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
  // Width of the Channels sidebar below — used to right-align the back/forward
  // buttons in the title bar with the sidebar's (and project switcher's) right edge.
  const channelsSidebarWidth = useChannelsSidebarStore((state) => state.width);
  // Suppress the title-bar width transition during a live drag so it tracks
  // the sidebar frame-for-frame; when the sidebar toggles open/closed, both
  // animate with the same curve (see ResizableSidebar).
  const sidebarIsResizing = useChannelsSidebarStore(
    (state) => state.isResizing,
  );
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

  // "PostHog Web" opens the feedback modal first and performs its navigation
  // only once the modal is submitted or skipped.
  const handleFeedbackFinished = () => {
    const finishedMode = feedbackMode;
    setFeedbackMode(null);
    if (finishedMode === "posthog-web" && posthogWebUrl) {
      void openUrlInBrowser(posthogWebUrl);
    }
  };

  const handleOpenPostHogWeb = () => {
    track(ANALYTICS_EVENTS.POSTHOG_WEB_OPENED);
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
  const syncCloudTasksEnabled = useFeatureFlag(SYNC_CLOUD_TASKS_FLAG);
  // "PostHog Web" is a channels-world affordance — show it only while the user
  // is actually seeing channels (toggle on, which itself requires the flag).
  const bluebirdEnabled = useFeatureFlag(
    PROJECT_BLUEBIRD_FLAG,
    import.meta.env.DEV,
  );
  const channelsToggleOn = useSidebarStore((s) => s.channelsEnabled);
  const channelsEnabled = channelsToggleOn && bluebirdEnabled;
  // When the sidebar is collapsed (Cmd+B) the title bar's left block shrinks to
  // fit its own controls so the tab strip flushes left with the content pane.
  const sidebarOpen = useSidebarStore((s) => s.open);
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
  const approvalDeepLink = useApprovalDeepLink();
  useSetupDiscovery();
  useNewTaskDeepLink();

  // hydrateTask is no longer needed — the URL is the source of truth and the
  // task cache populates the route automatically.

  useEffect(() => {
    if (!syncCloudTasksEnabled) return;
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
  }, [
    syncCloudTasksEnabled,
    tasks,
    workspaces,
    workspacesFetched,
    queryClient,
    hostClient,
    trpc,
  ]);

  // Flags resolve asynchronously — flag-gated routes below wait for this
  // before redirecting away from a restored route the user can't access.
  const [flagsLoaded, setFlagsLoaded] = useState(false);
  useEffect(() => onFeatureFlagsLoaded(() => setFlagsLoaded(true)), []);

  // Settings is a full-page route — drop the app chrome (header/sidebar/
  // space-switcher) so the panel occupies the full window.
  const isSettingsRoute = useRouterState({
    select: (s) => s.matches.some((m) => m.routeId.startsWith("/settings")),
  });

  // The Bluebird chrome is the app shell for every non-settings route now. The
  // /website (Channels) routes own their own in-pane header (WebsiteLayout), so
  // the shared ContentHeader is mounted only outside that space.
  const onWebsitePath = useRouterState({
    select: (s) =>
      s.location.pathname === "/website" ||
      s.location.pathname.startsWith("/website/"),
  });

  // The /website (Channels) routes stay registered regardless of the flag, so a
  // stale URL, a restored session, or a persisted channel browser tab could
  // strand a flag-off user on the channel layout with no way back (the Channels
  // toggle is hidden and ContentHeader is suppressed on /website). Once flags
  // resolve, send them back to Code.
  useEffect(() => {
    if (flagsLoaded && !bluebirdEnabled && onWebsitePath) {
      openTaskInput();
    }
  }, [flagsLoaded, bluebirdEnabled, onWebsitePath]);

  // A blank browser tab (the "+" new-tab page) shows an empty placeholder — but
  // ONLY on the channels index. Inside a channel (`/website/$channelId…`) the
  // route owns the content (channel home, inbox, artifacts, a canvas, …), so the
  // placeholder must never replace it, otherwise channel navigation looks dead.
  const onChannelsIndex = useRouterState({
    select: (s) => s.location.pathname === "/website",
  });
  const activeTabBlank = useActiveTabIsBlank();
  const showBlankTab = onChannelsIndex && activeTabBlank;

  if (isSettingsRoute) {
    return (
      <Flex direction="column" height="100%">
        <ConnectivityBanner />
        <Outlet />
        <CommandMenu open={commandMenuOpen} onOpenChange={setCommandMenuOpen} />
        <GlobalFilePicker />
        <KeyboardShortcutsSheet
          open={shortcutsSheetOpen}
          onOpenChange={(open) => (open ? null : closeShortcutsSheet())}
        />
        <GlobalEventHandlers
          onToggleCommandMenu={toggleCommandMenu}
          onToggleShortcutsSheet={toggleShortcutsSheet}
        />
        {billingEnabled && <UsageLimitModal />}
        <UsageBillingAnnouncementModal />
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
            mark. The left section matches the sidebar width so the tab strip
            starts flush with the content pane; its padding clears the macOS
            stoplights via env(titlebar-area-x), the system-reported right
            edge of the traffic-light strip (see titleBarOverlay in
            window.ts). */}
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
            justify="between"
            gap="3"
            className="shrink-0 pr-2"
            style={{
              // Traffic-light size varies by macOS version, so a fixed inset
              // over- or under-shoots; the env var fallback covers hosts
              // without Window Controls Overlay.
              paddingLeft: isMac ? "env(titlebar-area-x, 78px)" : "78px",
              width: sidebarOpen ? channelsSidebarWidth : undefined,
              // Same curve/duration as ResizableSidebar's SLIDE_EASING so the
              // title bar tracks the sidebar edge.
              transition: sidebarIsResizing
                ? "none"
                : "width 0.2s cubic-bezier(0, 0, 0.2, 1)",
            }}
          >
            <Flex align="center" gap="2" className="no-drag">
              <Box className="h-[14px] w-[30px] overflow-hidden [&>svg]:h-[14px] [&>svg]:w-auto">
                <LogosLandscape code={false} />
              </Box>
              <Button
                variant="outline"
                size="icon-sm"
                aria-label="Toggle sidebar"
                onClick={handleToggleSidebar}
                onMouseEnter={() => {
                  if (!sidebarOpen) beginSidebarPeek();
                }}
              >
                {sidebarOpen ? (
                  <SidebarClose size={10} />
                ) : (
                  <SidebarOpen size={10} />
                )}
              </Button>
            </Flex>
            {localWorkspaces && (
              <Flex align="center" gap="2" className="no-drag">
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
              </Flex>
            )}
          </Flex>
          {/* Tabs work in both spaces: channel tabs under /website and plain
              task tabs in the Code experience. The strip's route→tab effect
              noops on param-less routes (inbox, agents, new-task), so it's safe
              to mount everywhere. */}
          <BrowserTabStrip />
          {/* Gated so an empty right-side group can't claim a no-drag rect
              in the title bar for nothing — every pixel without controls
              should drag the window. */}
          {(billingEnabled || channelsEnabled) && (
            <Flex align="center" gap="2" className="no-drag ml-auto pr-3">
              <UsageButton />
              {channelsEnabled && (
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
              // The radix preset replaces Tailwind's palette, so plain
              // `bg-black/*` doesn't exist — use the radix black-alpha scale
              // (--black-a2 = 10%, --black-a5 = 30%).
              className={`pointer-events-none absolute inset-0 z-40 bg-blackA-2 transition-opacity duration-200 ease-out motion-reduce:transition-none dark:bg-blackA-5 ${
                sidebarPeek ? "opacity-100" : "opacity-0"
              }`}
            />
          )}
          <ChannelsSidebar />
          {/* Content sits in a bordered, rounded card inset from the window
              edges — the framed pane from the design. */}
          <Box flexGrow="1" className="overflow-hidden">
            <Box
              className={`h-full overflow-hidden border-border border-t border-l bg-background ${
                sidebarOpen ? "rounded-tl-sm" : ""
              }`}
            >
              <Flex direction="column" height="100%">
                {/* The /website space renders its own header (WebsiteLayout);
                      everywhere else the shared header carries the view title
                      and, on a task, its action row. */}
                {!onWebsitePath && <ContentHeader />}
                <Box flexGrow="1" overflow="hidden">
                  {showBlankTab ? <BlankTabView /> : <Outlet />}
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
          onToggleCommandMenu={toggleCommandMenu}
          onToggleShortcutsSheet={toggleShortcutsSheet}
        />
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
        <UsageBillingAnnouncementModal />
        <UpdateAvailableModal />
        <WhatsNewModal />
        <RemoteBranchCheckoutDialog />
        <FeedbackModal
          mode={feedbackMode}
          onFinished={handleFeedbackFinished}
        />
        {approvalDeepLink.pending ? (
          <DeepLinkApprovalModal
            pending={approvalDeepLink.pending}
            onClose={approvalDeepLink.clear}
          />
        ) : null}
        <ExistingWorktreeDialog />
        <HedgehogMode />
      </Flex>
    </BrowserTabsDndProvider>
  );
}
