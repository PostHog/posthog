import type { ExternalAppType } from "./schemas";

export interface AppDefinition {
  type: ExternalAppType;
  darwin?: { path: string };
  win32?: { paths: string[]; exeName?: string };
}

export interface ExternalAppsPreferences {
  lastUsedApp?: string;
}
