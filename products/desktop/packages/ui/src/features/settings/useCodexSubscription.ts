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
import { useQuery } from "@tanstack/react-query";

export interface CodexSubscriptionStatus {
  cliInstalled: boolean;
  credentialFilePresent: boolean;
  appLoggedIn: boolean;
}

export function shouldShowCodexSubscriptionControls(input: {
  flagEnabled: boolean;
  adapter: Adapter | undefined;
  status: CodexSubscriptionStatus | undefined;
  subscriptionOn: boolean;
}): boolean {
  if (!input.flagEnabled || input.adapter !== "codex") return false;
  if (input.subscriptionOn) return true;
  const { status } = input;
  if (!status) return false;
  return (
    status.cliInstalled || status.credentialFilePresent || status.appLoggedIn
  );
}

export function effectiveCodexModelAccess(input: {
  flagEnabled: boolean;
  subscriptionOn: boolean;
  loggedIn: boolean;
  workspaceMode: "local" | "worktree" | "cloud";
}): CodexModelAccess {
  const onOwnPlan =
    input.flagEnabled &&
    input.subscriptionOn &&
    input.loggedIn &&
    input.workspaceMode !== "cloud";
  return onOwnPlan ? "own-subscription" : "posthog-gateway";
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
): Promise<void> {
  await settingsHydrated();
  const status = await fetchStatus();
  registerCodexSubscription({
    access: useSettingsStore.getState().codexModelAccess,
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
  const hostTRPC = useHostTRPC();
  const { data: status } = useQuery({
    ...hostTRPC.agent.codexSubscriptionStatus.queryOptions(),
    enabled: flagEnabled,
  });

  const subscriptionOn = codexModelAccess === "own-subscription";
  const loggedIn = status?.appLoggedIn === true;

  return {
    flagEnabled,
    subscriptionOn,
    status,
    loggedIn,
    needsConnection: flagEnabled && subscriptionOn && !loggedIn,
    setSubscriptionOn: (on) =>
      applyCodexModelAccess(
        on ? "own-subscription" : "posthog-gateway",
        loggedIn,
      ),
  };
}
