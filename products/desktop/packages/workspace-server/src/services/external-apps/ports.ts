import type { ExternalAppsPreferences } from "./types";

export interface ExternalAppsStore {
  getPrefs(): ExternalAppsPreferences;
  setPrefs(prefs: ExternalAppsPreferences): void;
}
