import { useHostTRPC } from "@posthog/host-router/react";
import {
  type Adapter,
  ANALYTICS_EVENTS,
  CLAUDE_OWN_SUBSCRIPTION_FLAG,
  type ModelAccess,
} from "@posthog/shared";
import { useFeatureFlag } from "@posthog/ui/features/feature-flags/useFeatureFlag";
import { useSettingsStore } from "@posthog/ui/features/settings/settingsStore";
import { track } from "@posthog/ui/shell/analytics";
import { registerClaudeSubscription } from "@posthog/ui/shell/posthogAnalyticsImpl";
import { useHostCapabilities } from "@posthog/ui/shell/useHostCapabilities";
import { useQuery } from "@tanstack/react-query";

export interface ClaudeSubscriptionStatus {
  loggedIn: boolean;
}

export function shouldShowClaudeSubscriptionControls(input: {
  flagEnabled: boolean;
  adapter: Adapter | undefined;
}): boolean {
  return input.flagEnabled && input.adapter === "claude";
}

export function claudeNeedsConnection(input: {
  flagEnabled: boolean;
  subscriptionOn: boolean;
  status: ClaudeSubscriptionStatus | undefined;
}): boolean {
  return (
    input.flagEnabled &&
    input.subscriptionOn &&
    input.status?.loggedIn === false
  );
}

export function effectiveClaudeModelAccess(input: {
  flagEnabled: boolean;
  subscriptionOn: boolean;
  loggedIn: boolean;
  workspaceMode: "local" | "worktree" | "cloud";
}): ModelAccess {
  const usesOwnSubscription =
    input.flagEnabled &&
    input.subscriptionOn &&
    input.loggedIn &&
    input.workspaceMode !== "cloud";
  return usesOwnSubscription ? "own-subscription" : "posthog-gateway";
}

export function applyClaudeModelAccess(
  next: ModelAccess,
  connected: boolean,
): void {
  const prev = useSettingsStore.getState().claudeModelAccess;
  if (prev === next) return;
  useSettingsStore.getState().setClaudeModelAccess(next);
  track(ANALYTICS_EVENTS.SETTING_CHANGED, {
    setting_name: "claude_model_access",
    new_value: next,
    old_value: prev,
  });
  registerClaudeSubscription({ access: next, connected });
}

export async function registerClaudeSubscriptionAtBoot(
  fetchStatus: () => Promise<ClaudeSubscriptionStatus>,
  flagEnabled: boolean,
): Promise<void> {
  await settingsHydrated();
  const status = await fetchStatus();
  const access: ModelAccess = flagEnabled
    ? useSettingsStore.getState().claudeModelAccess
    : "posthog-gateway";
  registerClaudeSubscription({
    access,
    connected: status.loggedIn,
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

export interface ClaudeSubscription {
  flagEnabled: boolean;
  subscriptionOn: boolean;
  status: ClaudeSubscriptionStatus | undefined;
  loggedIn: boolean;
  needsConnection: boolean;
  setSubscriptionOn: (on: boolean) => void;
}

export function useClaudeSubscription(): ClaudeSubscription {
  const flagEnabled =
    useFeatureFlag(CLAUDE_OWN_SUBSCRIPTION_FLAG) || import.meta.env.DEV;
  const claudeModelAccess = useSettingsStore((s) => s.claudeModelAccess);
  const { localWorkspaces } = useHostCapabilities();
  const hostTRPC = useHostTRPC();
  const canQueryStatus = flagEnabled && localWorkspaces;
  const { data: status } = useQuery({
    ...hostTRPC.agent.claudeSubscriptionStatus.queryOptions(),
    enabled: canQueryStatus,
  });

  const subscriptionOn = claudeModelAccess === "own-subscription";
  const loggedIn = status?.loggedIn === true;

  return {
    flagEnabled,
    subscriptionOn,
    status,
    loggedIn,
    needsConnection: claudeNeedsConnection({
      flagEnabled,
      subscriptionOn,
      status,
    }),
    setSubscriptionOn: (on) =>
      applyClaudeModelAccess(
        on ? "own-subscription" : "posthog-gateway",
        loggedIn,
      ),
  };
}
