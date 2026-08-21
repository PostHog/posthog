import type { TabsSnapshot } from "@posthog/shared";
import { asc } from "drizzle-orm";
import { inject, injectable } from "inversify";
import { DATABASE_SERVICE } from "../identifiers";
import { browserTabs, browserWindows } from "../schema";
import type { DatabaseService } from "../service";

/**
 * Durable storage for the Channels browser-tab strips. The whole snapshot is
 * small (tens of rows), so each save is a transactional full replace — simple
 * and free of delta-merge bugs. Window order is encoded by `position`.
 */
export interface IBrowserTabsRepository {
  load(): TabsSnapshot;
  save(snapshot: TabsSnapshot): void;
}

@injectable()
export class BrowserTabsRepository implements IBrowserTabsRepository {
  constructor(
    @inject(DATABASE_SERVICE)
    private readonly databaseService: DatabaseService,
  ) {}

  private get db() {
    return this.databaseService.db;
  }

  load(): TabsSnapshot {
    const windowRows = this.db
      .select()
      .from(browserWindows)
      .orderBy(asc(browserWindows.position))
      .all();
    const tabRows = this.db.select().from(browserTabs).all();

    return {
      windows: windowRows.map((w) => ({
        id: w.id,
        isPrimary: w.isPrimary,
        bounds: w.bounds ?? null,
        activeTabId: w.activeTabId ?? null,
      })),
      tabs: tabRows.map((t) => ({
        id: t.id,
        windowId: t.windowId,
        dashboardId: t.dashboardId,
        taskId: t.taskId ?? null,
        channelId: t.channelId ?? null,
        channelSection: t.channelSection ?? null,
        appView: t.appView ?? null,
        position: t.position,
        scrollState: t.scrollState ?? null,
        createdAt: t.createdAt,
        lastActiveAt: t.lastActiveAt,
      })),
    };
  }

  save(snapshot: TabsSnapshot): void {
    const now = Date.now();
    this.db.transaction((tx) => {
      // Tabs first (FK), then windows.
      tx.delete(browserTabs).run();
      tx.delete(browserWindows).run();

      if (snapshot.windows.length > 0) {
        tx.insert(browserWindows)
          .values(
            snapshot.windows.map((w, i) => ({
              id: w.id,
              isPrimary: w.isPrimary,
              bounds: w.bounds ?? null,
              activeTabId: w.activeTabId ?? null,
              position: i,
              createdAt: now,
              updatedAt: now,
            })),
          )
          .run();
      }
      if (snapshot.tabs.length > 0) {
        tx.insert(browserTabs)
          .values(
            snapshot.tabs.map((t) => ({
              id: t.id,
              windowId: t.windowId,
              dashboardId: t.dashboardId,
              taskId: t.taskId ?? null,
              channelId: t.channelId ?? null,
              channelSection: t.channelSection ?? null,
              appView: t.appView ?? null,
              position: t.position,
              scrollState: t.scrollState ?? null,
              createdAt: t.createdAt,
              lastActiveAt: t.lastActiveAt,
            })),
          )
          .run();
      }
    });
  }
}
