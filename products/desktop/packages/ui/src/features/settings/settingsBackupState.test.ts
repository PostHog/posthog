import {
  flushRendererStateWrites,
  registerRendererStateStorage,
} from "@posthog/ui/shell/rendererStorage";
import { useThemeStore } from "@posthog/ui/shell/themeStore";
import { beforeEach, describe, expect, it } from "vitest";
import { settingsBackupState } from "./settingsBackupState";
import { useSettingsStore } from "./settingsStore";

const data = new Map<string, string>();
registerRendererStateStorage({
  getItem: (key) => data.get(key) ?? null,
  setItem: (key, value) => {
    data.set(key, value);
  },
  removeItem: (key) => {
    data.delete(key);
  },
});

beforeEach(async () => {
  await flushRendererStateWrites();
  data.clear();
  await useSettingsStore.persist.rehydrate();
  useSettingsStore.setState(useSettingsStore.getInitialState());
  useSettingsStore.getState().setHasHydrated(true);
  useThemeStore.getState().setTheme("light");
  await flushRendererStateWrites();
});

describe("settingsBackupState", () => {
  it.each([
    [undefined, "light"],
    ["dark", "dark"],
  ] as const)(
    "applies theme %s and saves imported values through normal persistence",
    async (theme, expectedTheme) => {
      const sounds = [
        {
          id: "portable",
          name: "Portable chime",
          dataUrl: "data:audio/wav;base64,UklGRg==",
          durationMs: 1000,
        },
      ];
      useSettingsStore.getState().setDefaultMessagingMode("steer");
      const storedBeforeImport = data.get("settings-storage");

      settingsBackupState.apply({
        settings: {
          completionSound: "custom:portable",
          completionVolume: 42,
          ...(theme === undefined ? {} : { theme }),
        },
        sounds,
      });

      expect(settingsBackupState.read()).toMatchObject({
        settings: {
          theme: expectedTheme,
          completionSound: "custom:portable",
          completionVolume: 42,
          defaultMessagingMode: "steer",
        },
        sounds,
      });
      expect(data.get("settings-storage")).toBe(storedBeforeImport);

      useSettingsStore.getState().setTipsEnabled(false);
      await flushRendererStateWrites();
      const persisted = JSON.parse(data.get("settings-storage") ?? "{}").state;
      expect(persisted).toMatchObject({
        customSounds: sounds,
        completionSound: "custom:portable",
        completionVolume: 42,
        defaultMessagingMode: "steer",
        tipsEnabled: false,
      });
      await useSettingsStore.persist.rehydrate();
      expect(settingsBackupState.read().sounds).toEqual(sounds);
      expect(useSettingsStore.getState().completionSound).toBe(
        "custom:portable",
      );
      expect(typeof useSettingsStore.getState().addCustomSound).toBe(
        "function",
      );
    },
  );
});
