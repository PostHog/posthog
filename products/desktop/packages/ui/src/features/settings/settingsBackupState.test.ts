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
});
