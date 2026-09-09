import type { SessionConfigOption } from "@agentclientprotocol/sdk";
import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const hostState = vi.hoisted(() => ({ query: vi.fn() }));
const flagState = vi.hoisted(() => ({ enabled: true }));
const settingsState = vi.hoisted(() => ({
  _hasHydrated: true,
  lastUsedModel: null as string | null,
  lastUsedReasoningEffort: null as string | null,
  lastUsedContextWindow: null as string | null,
  lastUsedFastMode: null as boolean | null,
  lastUsedInitialTaskMode: undefined as string | undefined,
  defaultInitialTaskMode: "",
  defaultReasoningEffort: undefined as string | undefined,
  lastUsedAdapter: undefined as string | undefined,
  setLastUsedContextWindow: vi.fn(),
  setLastUsedFastMode: vi.fn(),
  setState: vi.fn(),
}));

vi.mock("@posthog/host-router/react", () => {
  // Hoisted: refetch sits in an effect dependency array keyed on the client,
  // so a fresh object per render would re-run the fetch forever.
  const client = {
    agent: { getPreviewConfigOptions: { query: hostState.query } },
  };
  return { useHostTRPCClient: () => client };
});
vi.mock("../../auth/store", () => ({
  useAuthStateValue: (selector: (state: { cloudRegion: string }) => string) =>
    selector({ cloudRegion: "us" }),
  useAuthStateFetched: () => true,
}));
vi.mock("@posthog/ui/features/feature-flags/useFeatureFlag", () => ({
  useFeatureFlag: () => flagState.enabled,
}));
vi.mock("../../../shell/logger", () => ({
  logger: { scope: () => ({ warn: vi.fn(), error: vi.fn() }) },
}));
vi.mock("./useTaskRunDefaults", () => {
  // Hoisted: the hook sits in deriveSelection's dependency array, so a fresh
  // object per render would loop the derivation effect forever.
  const NO_DEFAULTS = {
    defaults: { runtime_adapter: null, model: null, reasoning_effort: null },
    isSettled: true,
  };
  return { useTaskRunDefaults: () => NO_DEFAULTS };
});
vi.mock("../../settings/settingsStore", () => ({
  useSettingsStore: Object.assign(
    (selector: (state: typeof settingsState) => unknown) =>
      selector(settingsState),
    {
      getState: () => settingsState,
      setState: (patch: Partial<typeof settingsState>) =>
        Object.assign(settingsState, patch),
    },
  ),
}));

import { usePreviewConfig } from "./usePreviewConfig";

const modelOption = (ids: string[]): SessionConfigOption[] => [
  {
    id: "model",
    name: "Model",
    type: "select",
    currentValue: ids[0] ?? "",
    options: ids.map((id) => ({ value: id, name: id })),
    category: "model",
  },
];

describe("usePreviewConfig", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    flagState.enabled = true;
    settingsState.lastUsedModel = null;
  });

  it("blocks on an empty model list and clears on a retry that returns models", async () => {
    hostState.query.mockResolvedValueOnce(modelOption([]));
    hostState.query.mockResolvedValueOnce(
      modelOption(["claude-opus-4-8", "gpt-5.5"]),
    );

    const { result } = renderHook(() => usePreviewConfig("claude"));

    await waitFor(() => {
      expect(result.current.isLoading).toBe(false);
    });
    expect(result.current.isModelListUnresolved).toBe(true);

    act(() => {
      result.current.retry();
    });
    expect(result.current.isLoading).toBe(true);

    await waitFor(() => {
      expect(result.current.modelOption?.currentValue).toBe("claude-opus-4-8");
    });
    expect(result.current.isModelListUnresolved).toBe(false);
    expect(hostState.query).toHaveBeenCalledTimes(2);
  });

  it("is resolved when the list arrives with models", async () => {
    hostState.query.mockResolvedValue(modelOption(["claude-opus-4-8"]));

    const { result } = renderHook(() => usePreviewConfig("claude"));

    await waitFor(() => {
      expect(result.current.isLoading).toBe(false);
    });
    expect(result.current.isModelListUnresolved).toBe(false);
    expect(result.current.modelOption?.currentValue).toBe("claude-opus-4-8");
  });
});
