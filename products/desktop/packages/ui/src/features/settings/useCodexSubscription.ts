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
  cliInstalled: boolean;
  credentialFilePresent: boolean;
  appLoggedIn: boolean;
}

export function shouldShowCodexSubscriptionControls(input: {
  flagEnabled: boolean;
  adapter: Adapter | undefined;
}): boolean {
  // The connect flow runs the bundled codex binary, so it needs no standalone
  // CLI on PATH and no existing ~/.codex credentials. Show the controls for any
  // codex user under the flag so a fresh ChatGPT user can reach sign-in.
  return input.flagEnabled && input.adapter === "codex";
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
  flagEnabled: boolean,
): Promise<void> {
  await settingsHydrated();
  const status = await fetchStatus();
  // Mirror the session gate: without the flag, sessions run on the gateway
  // regardless of the persisted setting, so report the gateway too. Otherwise a
  // user who opted in before a flag rollback keeps reporting own-subscription.
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
  const { data: status } = useQuery({
    ...hostTRPC.agent.codexSubscriptionStatus.queryOptions(),
    // Cloud-only hosts (web) have no local codex and no such host procedure, so
    // asking would fail with NOT_FOUND. Same gate GeneralSettings uses.
    enabled: flagEnabled && localWorkspaces,
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
