import type {
  SettingsBackupSnapshot,
  SettingsBackupState,
} from "@posthog/core/settings/settingsBackup";
import { useThemeStore } from "@posthog/ui/shell/themeStore";
import { useSettingsStore } from "./settingsStore";

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
    useSettingsStore.setState({ ...preferences, customSounds: sounds });
    if (theme !== undefined) useThemeStore.getState().setTheme(theme);
  },
};
