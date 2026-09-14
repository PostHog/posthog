import type {
  SettingsBackupSnapshot,
  SettingsBackupState,
} from "@posthog/core/settings/settingsBackup";
import { mergeSettingsBackupSounds } from "@posthog/core/settings/settingsBackup";
import { transactRendererStateWrite } from "@posthog/ui/shell/rendererStorage";
import { useThemeStore } from "@posthog/ui/shell/themeStore";
import { useSettingsStore } from "./settingsStore";

// Bounds the rebase loop below: sustained, unrelated settings edits could
// otherwise keep outrunning the import's own write indefinitely.
const MAX_REBASE_ATTEMPTS = 5;

export const settingsBackupState: SettingsBackupState = {
  read(): SettingsBackupSnapshot {
    const state = useSettingsStore.getState();
    if (!state._hasHydrated)
      throw new Error("Settings are still loading. Try again in a moment.");
    return {
      settings: { ...state, theme: useThemeStore.getState().theme },
      sounds: state.customSounds,
    };
  },
  async apply({ settings, sounds }: SettingsBackupSnapshot): Promise<void> {
    const { theme, ...preferences } = settings;
    const soundsBeforeImport = new Set(
      useSettingsStore.getState().customSounds.map((sound) => sound.id),
    );
    const importedSounds = sounds.filter(
      (sound) => !soundsBeforeImport.has(sound.id),
    );

    await transactRendererStateWrite("settings-storage", async (persist) => {
      const buildPersistedState = () => {
        const current = useSettingsStore.getState();
        const rebased = mergeSettingsBackupSounds(
          current.customSounds,
          importedSounds,
        );
        const rebasedPreferences = { ...preferences };
        if (rebasedPreferences.completionSound?.startsWith("custom:")) {
          const selectedId = rebasedPreferences.completionSound.slice(7);
          const remappedId = rebased.remappedIds.get(selectedId);
          if (remappedId) {
            rebasedPreferences.completionSound = `custom:${remappedId}`;
          } else if (!rebased.sounds.some((sound) => sound.id === selectedId)) {
            delete rebasedPreferences.completionSound;
          }
        }
        const next = {
          ...current,
          ...rebasedPreferences,
          customSounds: rebased.sounds,
        };
        const options = useSettingsStore.persist.getOptions();
        return {
          patch: {
            ...rebasedPreferences,
            customSounds: rebased.sounds,
          },
          value: JSON.stringify({
            state: options.partialize?.(next),
            version: options.version,
          }),
        };
      };

      let next = buildPersistedState();
      for (let attempt = 1; ; attempt++) {
        await persist(next.value);
        const latest = buildPersistedState();
        // Publish exactly what was just persisted, even at the attempt cap,
        // so live state never runs ahead of the durable copy on disk.
        if (latest.value === next.value || attempt >= MAX_REBASE_ATTEMPTS) {
          useSettingsStore.setState(next.patch);
          break;
        }
        next = latest;
      }
    });
    if (theme !== undefined) useThemeStore.getState().setTheme(theme);
  },
};
