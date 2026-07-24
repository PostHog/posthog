import { and, eq } from "drizzle-orm";
import { inject, injectable } from "inversify";
import { DATABASE_SERVICE } from "../identifiers";
import { authOrgProjectPreferences, authPreferences } from "../schema";
import type { DatabaseService } from "../service";

export type AuthPreference = typeof authPreferences.$inferSelect;
export type NewAuthPreference = typeof authPreferences.$inferInsert;
export type AuthOrgProjectPreference =
  typeof authOrgProjectPreferences.$inferSelect;
export type NewAuthOrgProjectPreference =
  typeof authOrgProjectPreferences.$inferInsert;

export interface PersistAuthPreferenceInput {
  accountKey: string;
  cloudRegion: "us" | "eu" | "dev";
  lastSelectedProjectId: number | null;
  lastSelectedOrgId: string | null;
}

export interface PersistAuthOrgProjectPreferenceInput {
  accountKey: string;
  cloudRegion: "us" | "eu" | "dev";
  orgId: string;
  lastSelectedProjectId: number;
}

export interface IAuthPreferenceRepository {
  get(
    accountKey: string,
    cloudRegion: "us" | "eu" | "dev",
  ): AuthPreference | null;
  save(input: PersistAuthPreferenceInput): AuthPreference;
  getOrgProject(
    accountKey: string,
    cloudRegion: "us" | "eu" | "dev",
    orgId: string,
  ): AuthOrgProjectPreference | null;
  saveOrgProject(
    input: PersistAuthOrgProjectPreferenceInput,
  ): AuthOrgProjectPreference;
}

const now = () => new Date().toISOString();

@injectable()
export class AuthPreferenceRepository implements IAuthPreferenceRepository {
  constructor(
    @inject(DATABASE_SERVICE)
    private readonly databaseService: DatabaseService,
  ) {}

  private get db() {
    return this.databaseService.db;
  }

  get(
    accountKey: string,
    cloudRegion: "us" | "eu" | "dev",
  ): AuthPreference | null {
    return (
      this.db
        .select()
        .from(authPreferences)
        .where(
          and(
            eq(authPreferences.accountKey, accountKey),
            eq(authPreferences.cloudRegion, cloudRegion),
          ),
        )
        .limit(1)
        .get() ?? null
    );
  }

  save(input: PersistAuthPreferenceInput): AuthPreference {
    const timestamp = now();
    const existing = this.get(input.accountKey, input.cloudRegion);

    const row: NewAuthPreference = {
      accountKey: input.accountKey,
      cloudRegion: input.cloudRegion,
      lastSelectedProjectId: input.lastSelectedProjectId,
      lastSelectedOrgId: input.lastSelectedOrgId,
      createdAt: existing?.createdAt ?? timestamp,
      updatedAt: timestamp,
    };

    if (existing) {
      this.db
        .update(authPreferences)
        .set(row)
        .where(
          and(
            eq(authPreferences.accountKey, input.accountKey),
            eq(authPreferences.cloudRegion, input.cloudRegion),
          ),
        )
        .run();
    } else {
      this.db.insert(authPreferences).values(row).run();
    }

    const saved = this.get(input.accountKey, input.cloudRegion);
    if (!saved) {
      throw new Error("Failed to persist auth preference");
    }
    return saved;
  }

  getOrgProject(
    accountKey: string,
    cloudRegion: "us" | "eu" | "dev",
    orgId: string,
  ): AuthOrgProjectPreference | null {
    return (
      this.db
        .select()
        .from(authOrgProjectPreferences)
        .where(
          and(
            eq(authOrgProjectPreferences.accountKey, accountKey),
            eq(authOrgProjectPreferences.cloudRegion, cloudRegion),
            eq(authOrgProjectPreferences.orgId, orgId),
          ),
        )
        .limit(1)
        .get() ?? null
    );
  }

  saveOrgProject(
    input: PersistAuthOrgProjectPreferenceInput,
  ): AuthOrgProjectPreference {
    const timestamp = now();
    const existing = this.getOrgProject(
      input.accountKey,
      input.cloudRegion,
      input.orgId,
    );

    const row: NewAuthOrgProjectPreference = {
      accountKey: input.accountKey,
      cloudRegion: input.cloudRegion,
      orgId: input.orgId,
      lastSelectedProjectId: input.lastSelectedProjectId,
      createdAt: existing?.createdAt ?? timestamp,
      updatedAt: timestamp,
    };

    if (existing) {
      this.db
        .update(authOrgProjectPreferences)
        .set(row)
        .where(
          and(
            eq(authOrgProjectPreferences.accountKey, input.accountKey),
            eq(authOrgProjectPreferences.cloudRegion, input.cloudRegion),
            eq(authOrgProjectPreferences.orgId, input.orgId),
          ),
        )
        .run();
    } else {
      this.db.insert(authOrgProjectPreferences).values(row).run();
    }

    const saved = this.getOrgProject(
      input.accountKey,
      input.cloudRegion,
      input.orgId,
    );
    if (!saved) {
      throw new Error("Failed to persist auth org project preference");
    }
    return saved;
  }
}
