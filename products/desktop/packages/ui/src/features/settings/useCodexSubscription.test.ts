import { describe, expect, it } from "vitest";
import {
  type CodexSubscriptionStatus,
  effectiveCodexModelAccess,
  shouldShowCodexSubscriptionControls,
} from "./useCodexSubscription";

const detected: CodexSubscriptionStatus = {
  cliInstalled: true,
  credentialFilePresent: false,
  appLoggedIn: false,
};
const nothing: CodexSubscriptionStatus = {
  cliInstalled: false,
  credentialFilePresent: false,
  appLoggedIn: false,
};

describe("codex subscription gating", () => {
  it.each([
    [
      "flag off hides everything",
      {
        flagEnabled: false,
        adapter: "codex" as const,
        status: detected,
        subscriptionOn: true,
      },
      false,
    ],
    [
      "claude harness hides everything",
      {
        flagEnabled: true,
        adapter: "claude" as const,
        status: detected,
        subscriptionOn: true,
      },
      false,
    ],
    [
      "codex without any detection stays hidden",
      {
        flagEnabled: true,
        adapter: "codex" as const,
        status: nothing,
        subscriptionOn: false,
      },
      false,
    ],
    [
      "codex with a detected install shows",
      {
        flagEnabled: true,
        adapter: "codex" as const,
        status: detected,
        subscriptionOn: false,
      },
      true,
    ],
    [
      "an activated setting always shows so it can be turned off",
      {
        flagEnabled: true,
        adapter: "codex" as const,
        status: nothing,
        subscriptionOn: true,
      },
      true,
    ],
  ])("%s", (_name, input, expected) => {
    expect(shouldShowCodexSubscriptionControls(input)).toBe(expected);
  });

  it.each([
    [
      "cloud tasks never bill the subscription",
      {
        flagEnabled: true,
        subscriptionOn: true,
        loggedIn: true,
        workspaceMode: "cloud" as const,
      },
      "posthog-gateway",
    ],
    [
      "not signed in falls back to the gateway",
      {
        flagEnabled: true,
        subscriptionOn: true,
        loggedIn: false,
        workspaceMode: "local" as const,
      },
      "posthog-gateway",
    ],
    [
      "flag off falls back to the gateway",
      {
        flagEnabled: false,
        subscriptionOn: true,
        loggedIn: true,
        workspaceMode: "local" as const,
      },
      "posthog-gateway",
    ],
    [
      "local on the subscription",
      {
        flagEnabled: true,
        subscriptionOn: true,
        loggedIn: true,
        workspaceMode: "local" as const,
      },
      "own-subscription",
    ],
    [
      "worktree on the subscription",
      {
        flagEnabled: true,
        subscriptionOn: true,
        loggedIn: true,
        workspaceMode: "worktree" as const,
      },
      "own-subscription",
    ],
  ])("%s", (_name, input, expected) => {
    expect(effectiveCodexModelAccess(input)).toBe(expected);
  });
});
