import {
  flushRendererStateWrites,
  registerRendererStateStorage,
} from "@posthog/ui/shell/rendererStorage";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { settingsBackupState } from "./settingsBackupState";
import { useSettingsStore } from "./settingsStore";

const data = new Map<string, string>();
const setItem = vi.fn(async (key: string, value: string) => {
  data.set(key, value);
});
registerRendererStateStorage({
  getItem: (key) => data.get(key) ?? null,
  setItem,
  removeItem: (key) => {
    data.delete(key);
  },
});

beforeEach(async () => {
  await flushRendererStateWrites();
  data.clear();
  setItem.mockClear();
  await useSettingsStore.persist.rehydrate();
});

describe("settingsBackupState", () => {
  it("persists imported audio before returning and restores it after rehydration", async () => {
    const sounds = [
      {
        id: "portable",
        name: "Portable chime",
        dataUrl: "data:audio/wav;base64,UklGRg==",
        durationMs: 1000,
      },
    ];
    await settingsBackupState.apply({
      settings: { completionSound: "custom:portable", completionVolume: 42 },
      sounds,
    });
    expect(
      JSON.parse(data.get("settings-storage") ?? "{}").state,
    ).toMatchObject({
      customSounds: sounds,
      completionSound: "custom:portable",
      completionVolume: 42,
    });
    await useSettingsStore.persist.rehydrate();
    expect(settingsBackupState.read().sounds).toEqual(sounds);
    expect(useSettingsStore.getState().completionSound).toBe("custom:portable");
    expect(typeof useSettingsStore.getState().addCustomSound).toBe("function");
  });

  it("leaves the live settings and sounds unchanged when persistence fails", async () => {
    const before = settingsBackupState.read();
    setItem.mockRejectedValueOnce(new Error("Disk full"));
    await expect(
      settingsBackupState.apply({
        settings: { completionVolume: 1 },
        sounds: [],
      }),
    ).rejects.toThrow("Disk full");
    expect(settingsBackupState.read()).toEqual(before);
  });

  it("rebases an import over settings and sounds changed while an older write is in flight", async () => {
    const removedDuringImport = {
      id: "remove-me",
      name: "Remove me",
      dataUrl: "data:audio/wav;base64,BAUG",
      durationMs: 700,
    };
    useSettingsStore.setState({
      completionSound: "none",
      completionVolume: 80,
      customSounds: [removedDuringImport],
      defaultMessagingMode: "queue",
      tipsEnabled: true,
    });
    await flushRendererStateWrites();
    data.clear();
    setItem.mockClear();

    let finishOlderWrite!: () => void;
    let finishImportWrite!: () => void;
    setItem
      .mockImplementationOnce(
        (key, value) =>
          new Promise<void>((resolve) => {
            finishOlderWrite = () => {
              data.set(key, value);
              resolve();
            };
          }),
      )
      .mockImplementationOnce(
        (key, value) =>
          new Promise<void>((resolve) => {
            finishImportWrite = () => {
              data.set(key, value);
              resolve();
            };
          }),
      );
    useSettingsStore.getState().setTipsEnabled(false);
    const flushing = flushRendererStateWrites();
    await vi.waitFor(() => expect(setItem).toHaveBeenCalledTimes(1));

    const importedSound = {
      id: "portable",
      name: "Portable chime",
      dataUrl: "data:audio/wav;base64,UklGRg==",
      durationMs: 1000,
    };
    const importing = settingsBackupState.apply({
      settings: { completionSound: "custom:portable", completionVolume: 42 },
      sounds: [removedDuringImport, importedSound],
    });
    const concurrentSound = {
      id: "portable",
      name: "Locally added chime",
      dataUrl: "data:audio/wav;base64,AQID",
      durationMs: 800,
    };
    useSettingsStore.getState().addCustomSound(concurrentSound);
    useSettingsStore.getState().setDefaultMessagingMode("steer");
    await flushRendererStateWrites();

    finishOlderWrite();
    await vi.waitFor(() => expect(setItem).toHaveBeenCalledTimes(2));
    const addedDuringImport = {
      id: "during-import",
      name: "Added during import",
      dataUrl: "data:audio/wav;base64,BwgJ",
      durationMs: 900,
    };
    useSettingsStore.getState().removeCustomSound(removedDuringImport.id);
    useSettingsStore.getState().addCustomSound(addedDuringImport);
    await flushRendererStateWrites();
    finishImportWrite();
    await Promise.all([flushing, importing]);
    const persisted = JSON.parse(data.get("settings-storage") ?? "{}").state;
    expect(persisted).toMatchObject({
      completionSound: "custom:portable-import-1",
      completionVolume: 42,
      defaultMessagingMode: "steer",
    });
    expect(persisted.customSounds).toEqual([
      concurrentSound,
      addedDuringImport,
      { ...importedSound, id: "portable-import-1" },
    ]);
    expect(useSettingsStore.getState()).toMatchObject(persisted);
  });

  it("stops rebasing at the attempt cap instead of chasing sustained concurrent edits forever", async () => {
    useSettingsStore.setState({
      completionVolume: 80,
      defaultMessagingMode: "queue",
    });
    await flushRendererStateWrites();
    data.clear();
    setItem.mockClear();

    // A settings edit races every attempt, so the rebase can never converge
    // on its own; it must stop at the cap instead of persisting forever. One
    // extra call covers the transaction's own trailing flush of that edit.
    for (let i = 0; i < 6; i++) {
      setItem.mockImplementationOnce(async (key, value) => {
        data.set(key, value);
        useSettingsStore
          .getState()
          .setDefaultMessagingMode(i % 2 === 0 ? "steer" : "queue");
      });
    }

    await settingsBackupState.apply({
      settings: { completionVolume: 42 },
      sounds: [],
    });

    expect(setItem.mock.calls.length).toBeLessThanOrEqual(6);
    expect(useSettingsStore.getState().completionVolume).toBe(42);
  });

  it("keeps concurrent edits live and pending when the import write fails", async () => {
    useSettingsStore.setState({
      completionSound: "none",
      completionVolume: 80,
      customSounds: [],
      defaultMessagingMode: "queue",
      tipsEnabled: true,
    });
    await flushRendererStateWrites();
    data.clear();
    setItem.mockClear();

    let finish!: () => void;
    setItem
      .mockImplementationOnce(
        (key, value) =>
          new Promise<void>((resolve) => {
            finish = () => {
              data.set(key, value);
              resolve();
            };
          }),
      )
      .mockRejectedValueOnce(new Error("Disk full"));
    useSettingsStore.getState().setTipsEnabled(false);
    const flushing = flushRendererStateWrites();
    await vi.waitFor(() => expect(setItem).toHaveBeenCalledTimes(1));

    const importing = settingsBackupState.apply({
      settings: { completionVolume: 1 },
      sounds: [
        {
          id: "imported",
          name: "Imported chime",
          dataUrl: "data:audio/wav;base64,UklGRg==",
          durationMs: 1000,
        },
      ],
    });
    const concurrentSound = {
      id: "local",
      name: "Local chime",
      dataUrl: "data:audio/wav;base64,AQID",
      durationMs: 800,
    };
    useSettingsStore.getState().addCustomSound(concurrentSound);
    useSettingsStore.getState().setDefaultMessagingMode("steer");

    finish();
    await flushing;
    await expect(importing).rejects.toThrow("Disk full");
    expect(useSettingsStore.getState()).toMatchObject({
      completionVolume: 80,
      customSounds: [concurrentSound],
      defaultMessagingMode: "steer",
    });
    await flushRendererStateWrites();
    expect(
      JSON.parse(data.get("settings-storage") ?? "{}").state,
    ).toMatchObject({
      completionVolume: 80,
      customSounds: [concurrentSound],
      defaultMessagingMode: "steer",
    });
  });
});
