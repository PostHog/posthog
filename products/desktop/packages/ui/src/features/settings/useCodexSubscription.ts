import { useHostTRPC } from "@posthog/host-router/react";
import {
  type Adapter,
  ANALYTICS_EVENTS,
  CODEX_OWN_SUBSCRIPTION_FLAG,
  type CodexModelAccess,
} from "@posthog/shared";
import { useFeatureFlag } from "@posthog/ui/features/feature-flags/useFeatureFlag";
import { useSettingsStore } from "@posthog/ui/features/settings/settingsStore";
import { track } from "@posthog/ui/shell/analytics";
import { registerCodexSubscription } from "@posthog/ui/shell/posthogAnalyticsImpl";
import { useHostCapabilities } from "@posthog/ui/shell/useHostCapabilities";
import { useQuery } from "@tanstack/react-query";

export interface CodexSubscriptionStatus {
  appLoggedIn: boolean;
}

export function shouldShowCodexSubscriptionControls(input: {
  flagEnabled: boolean;
  adapter: Adapter | undefined;
}): boolean {
  return input.flagEnabled && input.adapter === "codex";
}

export function codexNeedsConnection(input: {
  flagEnabled: boolean;
  subscriptionOn: boolean;
  status: CodexSubscriptionStatus | undefined;
}): boolean {
  return (
    input.flagEnabled &&
    input.subscriptionOn &&
    input.status?.appLoggedIn === false
  );
}

export function effectiveCodexModelAccess(input: {
  flagEnabled: boolean;
  subscriptionOn: boolean;
  loggedIn: boolean;
  workspaceMode: "local" | "worktree" | "cloud";
}): CodexModelAccess {
  const usesOwnSubscription =
    input.flagEnabled &&
    input.subscriptionOn &&
    input.loggedIn &&
    input.workspaceMode !== "cloud";
  return usesOwnSubscription ? "own-subscription" : "posthog-gateway";
}

export function applyCodexModelAccess(
  next: CodexModelAccess,
  connected: boolean,
): void {
  const prev = useSettingsStore.getState().codexModelAccess;
  if (prev === next) return;
  useSettingsStore.getState().setCodexModelAccess(next);
  track(ANALYTICS_EVENTS.SETTING_CHANGED, {
    setting_name: "codex_model_access",
    new_value: next,
    old_value: prev,
  });
  registerCodexSubscription({ access: next, connected });
}

export async function registerCodexSubscriptionAtBoot(
  fetchStatus: () => Promise<CodexSubscriptionStatus>,
  flagEnabled: boolean,
): Promise<void> {
  await settingsHydrated();
  const status = await fetchStatus();
  const access: CodexModelAccess = flagEnabled
    ? useSettingsStore.getState().codexModelAccess
    : "posthog-gateway";
  registerCodexSubscription({
    access,
    connected: status.appLoggedIn,
  });
}

function settingsHydrated(): Promise<void> {
  if (useSettingsStore.getState()._hasHydrated) return Promise.resolve();
  return new Promise((resolve) => {
    const unsubscribe = useSettingsStore.subscribe((state) => {
      if (state._hasHydrated) {
        unsubscribe();
        resolve();
      }
    });
  });
}

export interface CodexSubscription {
  flagEnabled: boolean;
  subscriptionOn: boolean;
  status: CodexSubscriptionStatus | undefined;
  loggedIn: boolean;
  needsConnection: boolean;
  setSubscriptionOn: (on: boolean) => void;
}

export function useCodexSubscription(): CodexSubscription {
  const flagEnabled =
    useFeatureFlag(CODEX_OWN_SUBSCRIPTION_FLAG) || import.meta.env.DEV;
  const codexModelAccess = useSettingsStore((s) => s.codexModelAccess);
  const { localWorkspaces } = useHostCapabilities();
  const hostTRPC = useHostTRPC();
  const canQueryStatus = flagEnabled && localWorkspaces;
  const { data: status } = useQuery({
    ...hostTRPC.agent.codexSubscriptionStatus.queryOptions(),
    enabled: canQueryStatus,
  });

  const subscriptionOn = codexModelAccess === "own-subscription";
  const loggedIn = status?.appLoggedIn === true;

  return {
    flagEnabled,
    subscriptionOn,
    status,
    loggedIn,
    needsConnection: codexNeedsConnection({
      flagEnabled,
      subscriptionOn,
      status,
    }),
    setSubscriptionOn: (on) =>
      applyCodexModelAccess(
        on ? "own-subscription" : "posthog-gateway",
        loggedIn,
      ),
  };
}
