type CloudRegion = "us" | "eu" | "dev";

import { eq } from "drizzle-orm";
import { inject, injectable } from "inversify";
import { DATABASE_SERVICE } from "../identifiers";
import { authSessions } from "../schema";
import type { DatabaseService } from "../service";

export type AuthSession = typeof authSessions.$inferSelect;
export type NewAuthSession = typeof authSessions.$inferInsert;

export interface PersistAuthSessionInput {
  refreshTokenEncrypted: string;
  cloudRegion: CloudRegion;
  selectedProjectId: number | null;
  scopeVersion: number;
}

export interface IAuthSessionRepository {
  getCurrent(): AuthSession | null;
  saveCurrent(input: PersistAuthSessionInput): AuthSession;
  clearCurrent(): void;
}

const CURRENT_AUTH_SESSION_ID = 1;
const byId = eq(authSessions.id, CURRENT_AUTH_SESSION_ID);
const now = () => new Date().toISOString();

@injectable()
export class AuthSessionRepository implements IAuthSessionRepository {
  constructor(
    @inject(DATABASE_SERVICE)
    private readonly databaseService: DatabaseService,
  ) {}

  private get db() {
    return this.databaseService.db;
  }

  getCurrent(): AuthSession | null {
    return (
      this.db.select().from(authSessions).where(byId).limit(1).get() ?? null
    );
  }

  saveCurrent(input: PersistAuthSessionInput): AuthSession {
    const timestamp = now();
    const existing = this.getCurrent();

    const row: NewAuthSession = {
      id: CURRENT_AUTH_SESSION_ID,
      refreshTokenEncrypted: input.refreshTokenEncrypted,
      cloudRegion: input.cloudRegion,
      selectedProjectId: input.selectedProjectId,
      scopeVersion: input.scopeVersion,
      createdAt: existing?.createdAt ?? timestamp,
      updatedAt: timestamp,
    };

    if (existing) {
      this.db.update(authSessions).set(row).where(byId).run();
    } else {
      this.db.insert(authSessions).values(row).run();
    }

    const saved = this.getCurrent();
    if (!saved) {
      throw new Error("Failed to persist current auth session");
    }
    return saved;
  }

  clearCurrent(): void {
    this.db.delete(authSessions).where(byId).run();
  }
}
