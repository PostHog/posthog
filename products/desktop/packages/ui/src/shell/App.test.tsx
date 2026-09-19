import type { AuthState } from "@posthog/core/auth/schemas";
import type { OrgConsent } from "@posthog/ui/features/consent/useOrgConsent";
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@posthog/ui/shell/analytics", () => ({
  captureException: vi.fn(),
}));
vi.mock("@posthog/ui/features/auth/authQueries", () => ({
  useAuthStateValue: (select: (state: AuthState) => unknown) =>
    select(authState as AuthState),
}));
vi.mock("@posthog/ui/features/consent/useOrgConsent", () => ({
  useOrgConsent: () => consent,
}));
vi.mock("@posthog/ui/features/auth/useAuthSession", () => ({
  useAuthSession: () => ({ isBootstrapped: true }),
}));
vi.mock("@posthog/ui/features/auth/authClient", () => ({
  useOptionalAuthenticatedClient: () => ({}),
}));
vi.mock("@posthog/ui/features/auth/useAuthMutations", () => ({
  useLogoutMutation: () => ({ isPending: false }),
  useRetryDesktopAccessMutation: () => ({ isPending: false }),
  useSelectProjectMutation: () => ({ isPending: false, isError: false }),
  useSwitchOrgMutation: () => ({ isPending: false, isError: false }),
}));
vi.mock("@posthog/ui/features/auth/useOrgRole", () => ({
  useIsOrgAdmin: () => ({ isAdmin: true }),
}));
vi.mock("@posthog/ui/features/onboarding/onboardingStore", () => ({
  useOnboardingStore: (
    select: (state: { hasCompletedOnboarding: boolean }) => unknown,
  ) => select({ hasCompletedOnboarding: true }),
}));
vi.mock("@posthog/ui/features/consent/consentAnalytics", () => ({
  useConsentAnalytics: () => {},
}));
vi.mock("@posthog/ui/features/canvas/hooks/useChannelsLayout", () => ({
  useChannelsLayout: () => true,
}));
vi.mock("@posthog/ui/features/canvas/stores/channelPaneStore", () => ({
  showChannelList: vi.fn(),
}));
vi.mock("@posthog/ui/features/canvas/stores/spaceTreeStore", () => ({
  useSpaceTreeStore: { getState: () => ({ expandSpace: vi.fn() }) },
}));
vi.mock("@posthog/ui/shell/startupLocation", () => ({
  resolveStartupLocation: async () => ({ href: "/", firstRun: null }),
  rememberStartupLocation: vi.fn(),
}));
vi.mock("@posthog/ui/shell/firstRun", () => ({ ensureSession: vi.fn() }));
vi.mock("@posthog/ui/shell/useAppVisibilityWatchdog", () => ({
  useAppVisibilityWatchdog: () => {},
}));
vi.mock("@posthog/ui/router/router", () => ({
  router: {
    history: { replace: vi.fn(), subscribe: () => () => {} },
    load: async () => {},
  },
}));
vi.mock("@tanstack/react-router", () => ({
  RouterProvider: () => <div data-testid="main-app" />,
}));
vi.mock("@posthog/ui/features/auth/components/ScopeReauthPrompt", () => ({
  ScopeReauthPrompt: () => null,
}));
vi.mock(
  "@posthog/ui/features/canvas/freeform/useCanvasGenerationToasts",
  () => ({ CanvasGenerationToaster: () => null }),
);
vi.mock("@posthog/ui/features/folder-picker/AddDirectoryDialog", () => ({
  AddDirectoryDialog: () => null,
}));
vi.mock("@posthog/ui/features/settings/SettingsDialog", () => ({
  SettingsDialog: () => null,
}));
vi.mock(
  "@posthog/ui/features/task-detail/components/PendingPromptRecovery",
  () => ({
    PendingPromptRecovery: () => null,
  }),
);

import { captureException } from "@posthog/ui/shell/analytics";
import App from "./App";

const satisfiedConsent: OrgConsent = {
  status: "resolved",
  organizationId: "org-1",
  needsAiConsent: false,
  needsBetaTerms: false,
  satisfied: true,
  retry: async () => {},
};

let authState: Partial<AuthState>;
let consent: OrgConsent;

function setAuth(overrides: Partial<AuthState> = {}): void {
  authState = {
    status: "authenticated",
    cloudRegion: "us",
    currentOrgId: "org-1",
    currentProjectId: 42,
    orgProjectsMap: {},
    desktopAccess: { status: "allowed", projectId: 42, reason: null },
    ...overrides,
  } as Partial<AuthState>;
}

describe("App loading gate", () => {
  beforeEach(() => {
    setAuth();
    consent = satisfiedConsent;
    vi.mocked(captureException).mockClear();
  });

  it("keeps the app on screen while consent rechecks for the same organization", async () => {
    // Clearing the auth-scoped queries consent reads sends consent back to
    // "loading" for an organization the app has already shown. The window
    // must not blink back to the loading screen.
    const view = render(<App />);
    expect(await screen.findByTestId("main-app")).toBeInTheDocument();

    consent = { status: "loading", organizationId: "org-1" };
    view.rerender(<App />);

    expect(screen.getByTestId("main-app")).toBeInTheDocument();
    expect(screen.queryByTestId("app-loading-shell")).not.toBeInTheDocument();
    expect(captureException).not.toHaveBeenCalled();
  });

  it("shows the loading screen while consent resolves for another organization", async () => {
    const view = render(<App />);
    expect(await screen.findByTestId("main-app")).toBeInTheDocument();

    setAuth({ currentOrgId: "org-2" });
    consent = { status: "loading" };
    view.rerender(<App />);

    expect(screen.getByTestId("app-loading-shell")).toBeInTheDocument();
    expect(screen.queryByTestId("main-app")).not.toBeInTheDocument();
  });
});
