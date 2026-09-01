import { describe, expect, it } from "vitest";
import {
  claudeNeedsConnection,
  effectiveClaudeModelAccess,
  shouldShowClaudeSubscriptionControls,
} from "./useClaudeSubscription";

const status = (loggedIn: boolean) => ({
  loggedIn,
});

describe("claude subscription gating", () => {
  it.each([
    [
      "flag off hides everything",
      { flagEnabled: false, adapter: "claude" as const },
      false,
    ],
    [
      "codex harness hides everything",
      { flagEnabled: true, adapter: "codex" as const },
      false,
    ],
    [
      "no adapter selected hides everything",
      { flagEnabled: true, adapter: undefined },
      false,
    ],
    [
      "claude under the flag shows so a fresh user can reach the login instructions",
      { flagEnabled: true, adapter: "claude" as const },
      true,
    ],
  ])("%s", (_name, input, expected) => {
    expect(shouldShowClaudeSubscriptionControls(input)).toBe(expected);
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
      "not logged in falls back to the gateway",
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
    expect(effectiveClaudeModelAccess(input)).toBe(expected);
  });

  it.each([
    [
      "unknown status while loading is not treated as logged out",
      { flagEnabled: true, subscriptionOn: true, status: undefined },
      false,
    ],
    [
      "confirmed logged out needs connection",
      { flagEnabled: true, subscriptionOn: true, status: status(false) },
      true,
    ],
    [
      "logged in does not need connection",
      { flagEnabled: true, subscriptionOn: true, status: status(true) },
      false,
    ],
    [
      "subscription off never needs connection",
      { flagEnabled: true, subscriptionOn: false, status: status(false) },
      false,
    ],
    [
      "flag off never needs connection",
      { flagEnabled: false, subscriptionOn: true, status: status(false) },
      false,
    ],
  ])("%s", (_name, input, expected) => {
    expect(claudeNeedsConnection(input)).toBe(expected);
  });
});
