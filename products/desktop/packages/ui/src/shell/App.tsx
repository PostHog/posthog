import { getAuthIdentity } from "@posthog/core/auth/authIdentity";
import { ToastProvider } from "@posthog/quill";
import { EXTERNAL_LINKS, isNotAuthenticatedError } from "@posthog/shared";
import { useOptionalAuthenticatedClient } from "@posthog/ui/features/auth/authClient";
import { useAuthStateValue } from "@posthog/ui/features/auth/authQueries";
import { AuthScreen } from "@posthog/ui/features/auth/components/AuthScreen";
import { DesktopAccessScreen } from "@posthog/ui/features/auth/components/DesktopAccessScreen";
import { ScopeReauthPrompt } from "@posthog/ui/features/auth/components/ScopeReauthPrompt";
import {
  useLogoutMutation,
  useRedeemInviteCodeMutation,
  useRetryDesktopAccessMutation,
  useSelectProjectMutation,
  useSwitchOrgMutation,
} from "@posthog/ui/features/auth/useAuthMutations";
import { useAuthSession } from "@posthog/ui/features/auth/useAuthSession";
import { useIsOrgAdmin } from "@posthog/ui/features/auth/useOrgRole";
import { CanvasGenerationToaster } from "@posthog/ui/features/canvas/freeform/useCanvasGenerationToasts";
import { useChannelsLayout } from "@posthog/ui/features/canvas/hooks/useChannelsLayout";
import { showChannelList } from "@posthog/ui/features/canvas/stores/channelPaneStore";
import { useSpaceTreeStore } from "@posthog/ui/features/canvas/stores/spaceTreeStore";
import { ConsentScreen } from "@posthog/ui/features/consent/ConsentScreen";
import { useConsentAnalytics } from "@posthog/ui/features/consent/consentAnalytics";
import { useOrgConsent } from "@posthog/ui/features/consent/useOrgConsent";
import { AddDirectoryDialog } from "@posthog/ui/features/folder-picker/AddDirectoryDialog";
import { ErrorDetailsDialog } from "@posthog/ui/features/notifications/ErrorDetailsDialog";
import { OnboardingFlow } from "@posthog/ui/features/onboarding/components/OnboardingFlow";
import { useOnboardingStore } from "@posthog/ui/features/onboarding/onboardingStore";
import { SettingsDialog } from "@posthog/ui/features/settings/SettingsDialog";
import { UpdateBanner } from "@posthog/ui/features/sidebar/components/UpdateBanner";
import { PendingPromptRecovery } from "@posthog/ui/features/task-detail/components/PendingPromptRecovery";
import { router } from "@posthog/ui/router/router";
import { AppLoadingScreen } from "@posthog/ui/shell/AppLoadingScreen";
import { ErrorBoundary } from "@posthog/ui/shell/ErrorBoundary";
import { ensureSession } from "@posthog/ui/shell/firstRun";
import { logger } from "@posthog/ui/shell/logger";
import { openExternalUrl } from "@posthog/ui/shell/openExternal";
import {
  rememberStartupLocation,
  resolveStartupLocation,
} from "@posthog/ui/shell/startupLocation";
import { useAppVisibilityWatchdog } from "@posthog/ui/shell/useAppVisibilityWatchdog";
import { RouterProvider } from "@tanstack/react-router";
import { AnimatePresence, motion } from "framer-motion";
import { type ReactNode, useEffect, useRef, useState } from "react";

interface AppProps {
  /** Host-provided dev diagnostics toolbar, docked below the app content. */
  devToolbar?: ReactNode;
}

const log = logger.scope("app");

function App({ devToolbar }: AppProps) {
  const { isBootstrapped } = useAuthSession();
  const authState = useAuthStateValue((state) => state);
  const hasCompletedOnboarding = useOnboardingStore(
    (state) => state.hasCompletedOnboarding,
  );
  const isAuthenticated = authState.status === "authenticated";
  const desktopAccess = authState.desktopAccess;
  const selectProjectMutation = useSelectProjectMutation();
  const switchOrgMutation = useSwitchOrgMutation();
  const retryDesktopAccessMutation = useRetryDesktopAccessMutation();
  const redeemInviteCodeMutation = useRedeemInviteCodeMutation();
  const logoutMutation = useLogoutMutation();
  const desktopAccessIsCurrent =
    desktopAccess.projectId === authState.currentProjectId;
  const hasDesktopAccess =
    desktopAccessIsCurrent && desktopAccess.status === "allowed";
  const switchError =
    selectProjectMutation.isError || switchOrgMutation.isError
      ? "Couldn't switch your selection. Try again."
      : null;
  // Analytics init + dev inbox console moved to host CONTRIBUTIONs
  // (AnalyticsBootContribution / InboxDemoDevContribution), started by
  // boot at boot.

  // Workspace, focus, and agent event listeners moved to their feature
  // CONTRIBUTIONs (WorkspaceEventsContribution / FocusEventsContribution
  // / AgentEventsContribution), started by boot at boot.

  const isBlockedByAccessPolicy =
    isAuthenticated &&
    desktopAccessIsCurrent &&
    ["blocked", "error"].includes(desktopAccess.status);
  const authenticatedClient = useOptionalAuthenticatedClient();
  const consent = useOrgConsent(isAuthenticated && hasDesktopAccess);
  const needsConsent =
    isAuthenticated &&
    hasCompletedOnboarding &&
    hasDesktopAccess &&
    consent.status === "resolved" &&
    !consent.satisfied;
  const isCheckingAccess =
    isAuthenticated &&
    hasCompletedOnboarding &&
    (!desktopAccessIsCurrent ||
      ["unchecked", "checking"].includes(desktopAccess.status) ||
      (hasDesktopAccess && consent.status === "loading"));
  const { isAdmin: isOrgAdmin } = useIsOrgAdmin();
  const isAdmin = isOrgAdmin === true;
  useConsentAnalytics(
    hasCompletedOnboarding ? consent : { status: "loading" },
    isAdmin,
    "standalone_gate",
  );

  const spacesLayoutEnabled = useChannelsLayout();
  // Read through a ref so a flag arriving mid-startup cannot re-run the resolve and replace
  // a route the user has already moved off.
  const spacesLayoutEnabledRef = useRef(spacesLayoutEnabled);
  spacesLayoutEnabledRef.current = spacesLayoutEnabled;

  const readyForMainApp =
    isBootstrapped &&
    isAuthenticated &&
    hasCompletedOnboarding &&
    hasDesktopAccess &&
    consent.status === "resolved" &&
    consent.satisfied;
  const startupIdentity = getAuthIdentity(authState);

  useEffect(() => {
    if (consent.status !== "resolved" || !consent.satisfied) return;
    if (!startupIdentity || !authenticatedClient) return;
    void ensureSession(startupIdentity, authenticatedClient);
  }, [consent, startupIdentity, authenticatedClient]);

  // Resolve and load the initial route before mounting the router. Reset when
  // the user leaves the main app so a later re-entry starts fresh.
  const [initialRouteLoaded, setInitialRouteLoaded] = useState(false);
  useEffect(() => {
    if (!readyForMainApp) {
      setInitialRouteLoaded(false);
      return;
    }
    if (initialRouteLoaded) return;
    if (!startupIdentity || !authenticatedClient) return;

    let cancelled = false;
    const loadInitialRoute = async (): Promise<void> => {
      try {
        const { href, firstRun } = await resolveStartupLocation(
          startupIdentity,
          authenticatedClient,
          spacesLayoutEnabledRef.current,
        );
        if (firstRun) {
          showChannelList({ keepForRoute: firstRun.generalChannelId });
          useSpaceTreeStore.getState().expandSpace(firstRun.generalChannelId);
        }
        router.history.replace(href);
        rememberStartupLocation(startupIdentity, href);
        await router.load();
      } catch (error) {
        log.error("Failed to load initial route", { error });
      } finally {
        if (!cancelled) setInitialRouteLoaded(true);
      }
    };
    void loadInitialRoute();

    return () => {
      cancelled = true;
    };
  }, [
    readyForMainApp,
    initialRouteLoaded,
    startupIdentity,
    authenticatedClient,
  ]);

  useEffect(() => {
    if (!initialRouteLoaded || !startupIdentity) return;
    return router.history.subscribe(({ location }) => {
      rememberStartupLocation(startupIdentity, location.href);
    });
  }, [initialRouteLoaded, startupIdentity]);

  const mainRef = useRef<HTMLDivElement>(null);
  // Mirrors the "main" branch of renderContent() below; keep the two in sync.
  const showingMainApp = readyForMainApp && initialRouteLoaded;
  useAppVisibilityWatchdog(mainRef, showingMainApp);

  // Single gate for every state where the whole app is still loading.
  if (
    !isBootstrapped ||
    isCheckingAccess ||
    (readyForMainApp && !initialRouteLoaded)
  ) {
    return <AppLoadingScreen />;
  }

  const renderContent = () => {
    if (!hasCompletedOnboarding && !isBlockedByAccessPolicy) {
      return (
        <motion.div
          key="onboarding"
          initial={{ opacity: 1 }}
          className="h-full"
        >
          <OnboardingFlow
            onOpenSupport={() => openExternalUrl(EXTERNAL_LINKS.discord)}
          />
        </motion.div>
      );
    }

    if (!isAuthenticated) {
      return (
        <motion.div key="auth" initial={{ opacity: 1 }} className="h-full">
          <AuthScreen />
        </motion.div>
      );
    }

    if (isBlockedByAccessPolicy) {
      return (
        <motion.div
          key="desktop-access"
          initial={{ opacity: 1 }}
          className="h-full"
        >
          <DesktopAccessScreen
            access={desktopAccess}
            orgProjectsMap={authState.orgProjectsMap}
            currentOrgId={authState.currentOrgId}
            currentProjectId={authState.currentProjectId}
            isSwitching={
              selectProjectMutation.isPending || switchOrgMutation.isPending
            }
            isRetrying={retryDesktopAccessMutation.isPending}
            isRedeemingInviteCode={redeemInviteCodeMutation.isPending}
            isLoggingOut={logoutMutation.isPending}
            switchError={switchError}
            redemptionError={redeemInviteCodeMutation.error?.message ?? null}
            onSelectOrganization={(organizationId) =>
              switchOrgMutation.mutate(organizationId)
            }
            onSelectProject={(projectId) =>
              selectProjectMutation.mutate(projectId)
            }
            onRedeemInviteCode={(inviteCode) =>
              redeemInviteCodeMutation.mutate(inviteCode)
            }
            onRetry={() => retryDesktopAccessMutation.mutate()}
            onLogout={() => logoutMutation.mutate()}
            onOpenSupport={() => openExternalUrl(EXTERNAL_LINKS.talkToHuman)}
          />
        </motion.div>
      );
    }

    if (consent.status === "error" || needsConsent) {
      return (
        <motion.div key="consent" initial={{ opacity: 1 }} className="h-full">
          <ConsentScreen
            banner={<UpdateBanner variant="compact" />}
            onOpenSupport={() => openExternalUrl(EXTERNAL_LINKS.discord)}
            settingsDialog={<SettingsDialog />}
          />
        </motion.div>
      );
    }

    return (
      <motion.div key="main" ref={mainRef} className="app-fade-in h-full">
        <RouterProvider router={router} />
        {/* Surfaces a toast when a backgrounded canvas generation finishes,
            from anywhere in the app. Sibling of the router so it stays mounted
            across every route (not just the canvas space). Renders null. */}
        <CanvasGenerationToaster />
        <PendingPromptRecovery />
      </motion.div>
    );
  };

  const content = renderContent();

  return (
    <ToastProvider>
      <ErrorBoundary
        name="App"
        resetKey={authState.status}
        shouldSuppress={isNotAuthenticatedError}
      >
        <div className="flex h-screen flex-col">
          <div className="relative min-h-0 flex-1 overflow-hidden">
            {isAuthenticated ? (
              <AnimatePresence mode="wait">{content}</AnimatePresence>
            ) : (
              content
            )}
            <ScopeReauthPrompt />
            <AddDirectoryDialog />
            <ErrorDetailsDialog />
          </div>
          {devToolbar}
        </div>
      </ErrorBoundary>
    </ToastProvider>
  );
}

export default App;
