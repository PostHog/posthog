import type {
  AuthSession,
  IAuthSessionRepository,
  PersistAuthSessionInput,
} from "./auth-session-repository";

export interface MockAuthSessionRepository extends IAuthSessionRepository {
  _session: AuthSession | null;
}

export function createMockAuthSessionRepository(): MockAuthSessionRepository {
  let session: AuthSession | null = null;

  const clone = (value: AuthSession | null): AuthSession | null =>
    value ? { ...value } : null;

  return {
    get _session() {
      return clone(session);
    },
    set _session(value) {
      session = clone(value);
    },
    getCurrent: () => clone(session),
    saveCurrent: (input: PersistAuthSessionInput) => {
      const timestamp = new Date().toISOString();
      session = {
        id: 1,
        refreshTokenEncrypted: input.refreshTokenEncrypted,
        cloudRegion: input.cloudRegion,
        selectedProjectId: input.selectedProjectId,
        scopeVersion: input.scopeVersion,
        createdAt: session?.createdAt ?? timestamp,
        updatedAt: timestamp,
      };
      return { ...session };
    },
    clearCurrent: () => {
      session = null;
    },
  };
}
