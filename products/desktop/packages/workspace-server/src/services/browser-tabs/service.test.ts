import type { BrowserTab, TabsSnapshot } from "@posthog/shared";
import { describe, expect, it } from "vitest";
import type { IBrowserTabsRepository } from "../../db/repositories/browser-tabs-repository";
import { BrowserTabsService } from "./service";

const blankTab = (overrides: Partial<BrowserTab> = {}): BrowserTab => ({
  id: "tab-1",
  windowId: "win-1",
  dashboardId: null,
  taskId: null,
  channelId: null,
  channelSection: null,
  appView: null,
  position: 100,
  scrollState: null,
  createdAt: 1,
  lastActiveAt: 1,
  ...overrides,
});

class FakeRepository implements IBrowserTabsRepository {
  saved: TabsSnapshot | null = null;
  constructor(private readonly initial: TabsSnapshot) {}
  load(): TabsSnapshot {
    return this.initial;
  }
  save(snapshot: TabsSnapshot): void {
    this.saved = snapshot;
  }
}

describe("BrowserTabsService boot invariants", () => {
  const bootCases: [string, TabsSnapshot][] = [
    ["empty store", { windows: [], tabs: [] }],
    [
      "window persisted with zero tabs",
      {
        windows: [
          { id: "win-1", isPrimary: true, bounds: null, activeTabId: null },
        ],
        tabs: [],
      },
    ],
  ];

  it.each(bootCases)(
    "seeds a primary window with at least one tab (%s)",
    (_name, initial) => {
      const repo = new FakeRepository(initial);
      const service = new BrowserTabsService(repo);

      const snapshot = service.getSnapshot();
      const primary = snapshot.windows.find((w) => w.isPrimary);
      expect(primary).toBeDefined();
      expect(snapshot.tabs.length).toBeGreaterThanOrEqual(1);
      expect(snapshot.tabs[0]?.windowId).toBe(primary?.id);
      // The healed snapshot is persisted so the invariant survives a restart.
      expect(repo.saved).toEqual(snapshot);
    },
  );

  it("leaves an already-populated snapshot untouched", () => {
    const initial: TabsSnapshot = {
      windows: [
        { id: "win-1", isPrimary: true, bounds: null, activeTabId: "tab-1" },
      ],
      tabs: [blankTab()],
    };
    const repo = new FakeRepository(initial);
    const service = new BrowserTabsService(repo);

    expect(service.getSnapshot()).toBe(initial);
    expect(repo.saved).toBeNull();
  });
});

describe("BrowserTabsService window-id healing", () => {
  it("newBlankTab lands in the primary window when the given id is unknown", () => {
    const repo = new FakeRepository({ windows: [], tabs: [] });
    const service = new BrowserTabsService(repo);
    const primaryId = service.getPrimaryWindowId();

    const snapshot = service.newBlankTab({
      windowId: "stale-window-id",
      tabId: "tab-new",
    });

    const created = snapshot.tabs.find((t) => t.id === "tab-new");
    expect(created?.windowId).toBe(primaryId);
  });

  it("openOrFocus lands in the primary window when the given id is unknown", () => {
    const repo = new FakeRepository({ windows: [], tabs: [] });
    const service = new BrowserTabsService(repo);
    const primaryId = service.getPrimaryWindowId();

    const snapshot = service.openOrFocus({
      windowId: "stale-window-id",
      dashboardId: "dash-1",
      taskId: null,
      channelId: null,
      tabId: "tab-open",
    });

    const created = snapshot.tabs.find((t) => t.id === "tab-open");
    expect(created?.windowId).toBe(primaryId);
  });
});
