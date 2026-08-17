import type {
  AuthOrgProjectPreference,
  AuthPreference,
  IAuthPreferenceRepository,
  PersistAuthOrgProjectPreferenceInput,
  PersistAuthPreferenceInput,
} from "./auth-preference-repository";

export interface MockAuthPreferenceRepository
  extends IAuthPreferenceRepository {
  _preferences: AuthPreference[];
  _orgProjectPreferences: AuthOrgProjectPreference[];
}

export function createMockAuthPreferenceRepository(): MockAuthPreferenceRepository {
  let preferences: AuthPreference[] = [];
  let orgProjectPreferences: AuthOrgProjectPreference[] = [];

  const clone = (value: AuthPreference): AuthPreference => ({ ...value });
  const cloneOrgProject = (
    value: AuthOrgProjectPreference,
  ): AuthOrgProjectPreference => ({ ...value });

  return {
    get _preferences() {
      return preferences.map(clone);
    },
    set _preferences(value) {
      preferences = value.map(clone);
    },
    get _orgProjectPreferences() {
      return orgProjectPreferences.map(cloneOrgProject);
    },
    set _orgProjectPreferences(value) {
      orgProjectPreferences = value.map(cloneOrgProject);
    },
    get: (accountKey, cloudRegion) => {
      const preference = preferences.find(
        (entry) =>
          entry.accountKey === accountKey && entry.cloudRegion === cloudRegion,
      );
      return preference ? clone(preference) : null;
    },
    save: (input: PersistAuthPreferenceInput) => {
      const timestamp = new Date().toISOString();
      const existingIndex = preferences.findIndex(
        (entry) =>
          entry.accountKey === input.accountKey &&
          entry.cloudRegion === input.cloudRegion,
      );

      const row: AuthPreference = {
        accountKey: input.accountKey,
        cloudRegion: input.cloudRegion,
        lastSelectedProjectId: input.lastSelectedProjectId,
        lastSelectedOrgId: input.lastSelectedOrgId,
        createdAt:
          existingIndex >= 0 ? preferences[existingIndex].createdAt : timestamp,
        updatedAt: timestamp,
      };

      if (existingIndex >= 0) {
        preferences[existingIndex] = row;
      } else {
        preferences.push(row);
      }

      return clone(row);
    },
    getOrgProject: (accountKey, cloudRegion, orgId) => {
      const preference = orgProjectPreferences.find(
        (entry) =>
          entry.accountKey === accountKey &&
          entry.cloudRegion === cloudRegion &&
          entry.orgId === orgId,
      );
      return preference ? cloneOrgProject(preference) : null;
    },
    saveOrgProject: (input: PersistAuthOrgProjectPreferenceInput) => {
      const timestamp = new Date().toISOString();
      const existingIndex = orgProjectPreferences.findIndex(
        (entry) =>
          entry.accountKey === input.accountKey &&
          entry.cloudRegion === input.cloudRegion &&
          entry.orgId === input.orgId,
      );

      const row: AuthOrgProjectPreference = {
        accountKey: input.accountKey,
        cloudRegion: input.cloudRegion,
        orgId: input.orgId,
        lastSelectedProjectId: input.lastSelectedProjectId,
        createdAt:
          existingIndex >= 0
            ? orgProjectPreferences[existingIndex].createdAt
            : timestamp,
        updatedAt: timestamp,
      };

      if (existingIndex >= 0) {
        orgProjectPreferences[existingIndex] = row;
      } else {
        orgProjectPreferences.push(row);
      }

      return cloneOrgProject(row);
    },
  };
}
