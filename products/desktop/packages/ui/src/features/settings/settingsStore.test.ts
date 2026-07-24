import {
  flushRendererStateWrites,
  registerRendererStateStorage,
} from "@posthog/ui/shell/rendererStorage";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  type CompletionSound,
  DEFAULT_WORKSPACE_MODE,
  getEffectiveCustomInstructions,
  useSettingsStore,
} from "./settingsStore";

const getItem = vi.fn();
const setItem = vi.fn();
const removeItem = vi.fn();

registerRendererStateStorage({ getItem, setItem, removeItem });

// Lands any coalesced write from the previous test on the old mocks (so a
// pending value cannot leak into this test's reads or assertions), then
// resets them.
async function resetPersistenceMocks() {
  await flushRendererStateWrites();
  getItem.mockReset();
  setItem.mockReset();
  removeItem.mockReset();
  getItem.mockResolvedValue(null);
  setItem.mockResolvedValue(undefined);
  removeItem.mockResolvedValue(undefined);
}

// Persisted writes are debounced; flush while polling so the assertion sees
// the coalesced write as soon as the store has queued it.
async function waitForPersistedWrite() {
  await vi.waitFor(async () => {
    await flushRendererStateWrites();
    expect(setItem).toHaveBeenCalled();
  });
}

// Runs before any test mutates the store singleton, so getState() still
// reflects the initial values.
describe("feature settingsStore defaults", () => {
  it("defaults the workspace mode to cloud with a local fallback", () => {
    expect(DEFAULT_WORKSPACE_MODE).toBe("cloud");
    expect(useSettingsStore.getState().lastUsedWorkspaceMode).toBe("cloud");
    expect(useSettingsStore.getState().lastUsedLocalWorkspaceMode).toBe(
      "local",
    );
  });
});

describe("feature settingsStore cloud selections", () => {
  beforeEach(async () => {
    await resetPersistenceMocks();

    useSettingsStore.setState({
      allowBypassPermissions: false,
      lastUsedCloudRepository: null,
      cachedCloudRepositoryMap: {},
      cachedCloudDefaultBranchMap: {},
    });
  });

  it("persists the last used cloud repository", async () => {
    useSettingsStore.getState().setLastUsedCloudRepository("posthog/posthog");

    await waitForPersistedWrite();

    const lastCall = setItem.mock.calls[setItem.mock.calls.length - 1];
    const persisted = JSON.parse(lastCall[1]);

    expect(persisted.state.lastUsedCloudRepository).toBe("posthog/posthog");
  });

  it("rehydrates the last used cloud repository", async () => {
    getItem.mockResolvedValue(
      JSON.stringify({
        state: {
          lastUsedCloudRepository: "posthog/posthog",
        },
        version: 0,
      }),
    );

    useSettingsStore.setState({
      lastUsedCloudRepository: null,
    });

    await useSettingsStore.persist.rehydrate();

    expect(useSettingsStore.getState().lastUsedCloudRepository).toBe(
      "posthog/posthog",
    );
  });

  it("persists the cached cloud repository map", async () => {
    useSettingsStore.getState().setCachedCloudRepositoryMap({
      "posthog/posthog": {
        userIntegrationId: "user-1",
        installationId: "install-1",
      },
    });

    await waitForPersistedWrite();

    const lastCall = setItem.mock.calls[setItem.mock.calls.length - 1];
    const persisted = JSON.parse(lastCall[1]);

    expect(persisted.state.cachedCloudRepositoryMap).toEqual({
      "posthog/posthog": {
        userIntegrationId: "user-1",
        installationId: "install-1",
      },
    });
  });

  it("rehydrates the cached cloud repository map", async () => {
    getItem.mockResolvedValue(
      JSON.stringify({
        state: {
          cachedCloudRepositoryMap: {
            "posthog/code": {
              userIntegrationId: "user-2",
              installationId: "install-2",
            },
          },
        },
        version: 0,
      }),
    );

    useSettingsStore.setState({ cachedCloudRepositoryMap: {} });

    await useSettingsStore.persist.rehydrate();

    expect(useSettingsStore.getState().cachedCloudRepositoryMap).toEqual({
      "posthog/code": {
        userIntegrationId: "user-2",
        installationId: "install-2",
      },
    });
  });

  it("caches and persists the cloud default branch per repo", async () => {
    useSettingsStore
      .getState()
      .setCachedCloudDefaultBranch("posthog/posthog", "master");
    useSettingsStore
      .getState()
      .setCachedCloudDefaultBranch("posthog/code", "main");

    expect(useSettingsStore.getState().cachedCloudDefaultBranchMap).toEqual({
      "posthog/posthog": "master",
      "posthog/code": "main",
    });

    await waitForPersistedWrite();

    const lastCall = setItem.mock.calls[setItem.mock.calls.length - 1];
    const persisted = JSON.parse(lastCall[1]);

    expect(persisted.state.cachedCloudDefaultBranchMap).toEqual({
      "posthog/posthog": "master",
      "posthog/code": "main",
    });
  });

  it("keeps the same map reference when the default branch is unchanged", () => {
    useSettingsStore
      .getState()
      .setCachedCloudDefaultBranch("posthog/code", "main");
    const first = useSettingsStore.getState().cachedCloudDefaultBranchMap;

    useSettingsStore
      .getState()
      .setCachedCloudDefaultBranch("posthog/code", "main");
    const second = useSettingsStore.getState().cachedCloudDefaultBranchMap;

    expect(second).toBe(first);
  });

  it("rehydrates the cached cloud default branch map", async () => {
    getItem.mockResolvedValue(
      JSON.stringify({
        state: {
          cachedCloudDefaultBranchMap: { "posthog/code": "main" },
        },
        version: 0,
      }),
    );

    useSettingsStore.setState({ cachedCloudDefaultBranchMap: {} });

    await useSettingsStore.persist.rehydrate();

    expect(useSettingsStore.getState().cachedCloudDefaultBranchMap).toEqual({
      "posthog/code": "main",
    });
  });

  it("rehydrates the unsafe mode toggle", async () => {
    getItem.mockResolvedValue(
      JSON.stringify({
        state: {
          allowBypassPermissions: true,
        },
        version: 0,
      }),
    );

    await useSettingsStore.persist.rehydrate();

    expect(useSettingsStore.getState().allowBypassPermissions).toBe(true);
  });

  it.each([
    ["lastUsedWorkspaceMode", "local", "cloud"],
    ["debugLogsCloudRuns", false, true],
    ["slotMachineMode", false, true],
    ["dismissibleUpdateBanners", false, true],
    ["showSidebarWorktrees", false, true],
  ] as const)("rehydrates %s", async (field, initial, persisted) => {
    getItem.mockResolvedValue(
      JSON.stringify({ state: { [field]: persisted }, version: 0 }),
    );

    useSettingsStore.setState({ [field]: initial } as Parameters<
      typeof useSettingsStore.setState
    >[0]);

    await useSettingsStore.persist.rehydrate();

    expect(useSettingsStore.getState()[field]).toBe(persisted);
  });

  it("flips _hasHydrated once the persisted snapshot lands", async () => {
    getItem.mockResolvedValue(JSON.stringify({ state: {}, version: 0 }));

    useSettingsStore.setState({ _hasHydrated: false });

    await useSettingsStore.persist.rehydrate();

    expect(useSettingsStore.getState()._hasHydrated).toBe(true);
  });
});

describe("feature settingsStore custom sounds", () => {
  beforeEach(async () => {
    await resetPersistenceMocks();

    useSettingsStore.setState({ customSounds: [], completionSound: "none" });
  });

  const sound = {
    id: "abc",
    name: "My ding",
    dataUrl: "data:audio/webm;base64,AAAA",
    durationMs: 1200,
  };

  it("adds a custom sound", () => {
    useSettingsStore.getState().addCustomSound(sound);
    expect(useSettingsStore.getState().customSounds).toEqual([sound]);
  });

  it("renames a custom sound without touching its clip", () => {
    useSettingsStore.getState().addCustomSound(sound);
    useSettingsStore.getState().renameCustomSound("abc", "Renamed");
    const stored = useSettingsStore.getState().customSounds[0];
    expect(stored.name).toBe("Renamed");
    expect(stored.dataUrl).toBe(sound.dataUrl);
  });

  it.each([
    {
      label: "active sound",
      activeSound: "custom:abc" as CompletionSound,
      expectedSound: "none" as CompletionSound,
    },
    {
      label: "non-active sound",
      activeSound: "meep" as CompletionSound,
      expectedSound: "meep" as CompletionSound,
    },
    {
      label: "last sound feeding random-custom",
      activeSound: "random-custom" as CompletionSound,
      expectedSound: "none" as CompletionSound,
    },
  ])(
    "removing the $label leaves completionSound as $expectedSound",
    ({ activeSound, expectedSound }) => {
      useSettingsStore.getState().addCustomSound(sound);
      useSettingsStore.getState().setCompletionSound(activeSound);
      useSettingsStore.getState().removeCustomSound("abc");
      expect(useSettingsStore.getState().customSounds).toEqual([]);
      expect(useSettingsStore.getState().completionSound).toBe(expectedSound);
    },
  );

  it("keeps random-custom active while other custom sounds remain", () => {
    useSettingsStore.getState().addCustomSound(sound);
    useSettingsStore.getState().addCustomSound({ ...sound, id: "def" });
    useSettingsStore.getState().setCompletionSound("random-custom");
    useSettingsStore.getState().removeCustomSound("abc");
    expect(useSettingsStore.getState().completionSound).toBe("random-custom");
  });

  it("persists custom sounds", async () => {
    useSettingsStore.getState().addCustomSound(sound);

    await waitForPersistedWrite();

    const lastCall = setItem.mock.calls[setItem.mock.calls.length - 1];
    const persisted = JSON.parse(lastCall[1]);
    expect(persisted.state.customSounds).toEqual([sound]);
  });

  it.each([
    {
      label: "random-custom with empty customSounds array",
      persistedState: { completionSound: "random-custom", customSounds: [] },
      expectedCompletionSound: "none",
    },
    {
      label: "random-custom with absent customSounds key",
      persistedState: { completionSound: "random-custom" },
      expectedCompletionSound: "none",
    },
    {
      label: "random-custom with non-empty library",
      persistedState: {
        completionSound: "random-custom",
        customSounds: [sound],
      },
      expectedCompletionSound: "random-custom",
    },
  ])(
    "rehydrate merge normalizes $label",
    async ({ persistedState, expectedCompletionSound }) => {
      getItem.mockResolvedValue(
        JSON.stringify({ state: persistedState, version: 0 }),
      );

      await useSettingsStore.persist.rehydrate();

      expect(useSettingsStore.getState().completionSound).toBe(
        expectedCompletionSound,
      );
    },
  );
});

describe("getEffectiveCustomInstructions", () => {
  const synced = {
    path: "/home/u/.claude/CLAUDE.md",
    displayPath: "~/.claude/CLAUDE.md",
    content: "from file",
    truncated: false,
  };

  it.each([
    {
      label: "typed instructions when sync is off",
      sync: false,
      syncedValue: synced,
      expected: "typed",
    },
    {
      label: "file content when sync is on and a file was found",
      sync: true,
      syncedValue: synced,
      expected: "from file",
    },
    {
      label: "nothing when sync is on but no file was found",
      sync: true,
      syncedValue: null,
      expected: "",
    },
    {
      label: "nothing when the synced file is whitespace",
      sync: true,
      syncedValue: { ...synced, content: " \n" },
      expected: "",
    },
  ])("returns $label", ({ sync, syncedValue, expected }) => {
    expect(
      getEffectiveCustomInstructions({
        customInstructions: "typed",
        syncCustomInstructionsFromFile: sync,
        syncedCustomInstructions: syncedValue,
      }),
    ).toBe(expected);
  });
});

describe("feature settingsStore custom instructions sync persistence", () => {
  beforeEach(async () => {
    await resetPersistenceMocks();

    useSettingsStore.setState({
      syncCustomInstructionsFromFile: false,
      syncedCustomInstructions: null,
    });
  });

  it("persists the sync toggle but never the runtime snapshot", async () => {
    // The toggle is durable preference; the snapshot is re-read on boot by the
    // sync contribution. Persisting the snapshot would let a stale file rehydrate
    // and reach a session created before the contribution's re-read finishes.
    useSettingsStore.setState({
      syncCustomInstructionsFromFile: true,
      syncedCustomInstructions: {
        path: "/home/u/.claude/CLAUDE.md",
        displayPath: "~/.claude/CLAUDE.md",
        content: "from file",
        truncated: false,
      },
    });
    // Nudge a persisted write via a partialized field.
    useSettingsStore.getState().setCustomInstructions("touch");

    await waitForPersistedWrite();

    const lastCall = setItem.mock.calls[setItem.mock.calls.length - 1];
    const persisted = JSON.parse(lastCall[1]);

    expect(persisted.state.syncCustomInstructionsFromFile).toBe(true);
    expect(persisted.state).not.toHaveProperty("syncedCustomInstructions");
  });
});

describe("feature settingsStore terminal font", () => {
  beforeEach(async () => {
    await resetPersistenceMocks();

    useSettingsStore.setState({
      terminalFont: "berkeley-mono",
      terminalCustomFontFamily: "",
    });
  });

  it("defaults to berkeley-mono with no custom override", () => {
    expect(useSettingsStore.getState().terminalFont).toBe("berkeley-mono");
    expect(useSettingsStore.getState().terminalCustomFontFamily).toBe("");
  });

  it("persists terminal font selection and custom family", async () => {
    useSettingsStore.getState().setTerminalFont("custom");
    useSettingsStore.getState().setTerminalCustomFontFamily("Fira Code");

    await waitForPersistedWrite();

    const lastCall = setItem.mock.calls[setItem.mock.calls.length - 1];
    const persisted = JSON.parse(lastCall[1]);

    expect(persisted.state.terminalFont).toBe("custom");
    expect(persisted.state.terminalCustomFontFamily).toBe("Fira Code");
  });

  it("rehydrates terminal font selection and custom family", async () => {
    getItem.mockResolvedValue(
      JSON.stringify({
        state: {
          terminalFont: "jetbrains-mono",
          terminalCustomFontFamily: "Cascadia Code",
        },
        version: 0,
      }),
    );

    await useSettingsStore.persist.rehydrate();

    expect(useSettingsStore.getState().terminalFont).toBe("jetbrains-mono");
    expect(useSettingsStore.getState().terminalCustomFontFamily).toBe(
      "Cascadia Code",
    );
  });
});
