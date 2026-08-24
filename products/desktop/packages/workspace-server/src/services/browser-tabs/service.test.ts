import type { BrowserTab, TabsSnapshot } from "@posthog/shared";
import { describe, expect, it } from "vitest";
import type { IBrowserTabsRepository } from "../../db/repositories/browser-tabs-repository";
import { NEW_TAB_HREF } from "./schemas";
import { BrowserTabsService } from "./service";

const blankTab = (overrides: Partial<BrowserTab> = {}): BrowserTab => ({
  id: "tab-1",
  windowId: "win-1",
  href: null,
  viewState: null,
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
    return this.saved ?? this.initial;
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
      // On the new-tab page, not a location-less tab that would render nothing.
      expect(snapshot.tabs[0]?.href).toBe(NEW_TAB_HREF);
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

  it("restores a resolved tab title after the service is recreated", () => {
    const repo = new FakeRepository({
      windows: [
        { id: "win-1", isPrimary: true, bounds: null, activeTabId: "tab-1" },
      ],
      tabs: [blankTab()],
    });
    const service = new BrowserTabsService(repo);

    service.openTab({
      windowId: "win-1",
      tabId: "tab-2",
      href: "/tasks/task-2",
      viewState: { title: "Investigate checkout drop-off" },
      dashboardId: null,
      taskId: "task-2",
      channelId: null,
    });

    const restarted = new BrowserTabsService(repo);
    expect(
      restarted.getSnapshot().tabs.find((tab) => tab.id === "tab-2")?.viewState
        ?.title,
    ).toBe("Investigate checkout drop-off");
  });

  it("clears persisted locations and titles when the auth scope changes", () => {
    const initial: TabsSnapshot = {
      windows: [
        { id: "win-1", isPrimary: true, bounds: null, activeTabId: "tab-1" },
      ],
      tabs: [
        blankTab({
          href: "/tasks/private-task",
          viewState: {
            title: "Private task title",
            lastByPane: {
              inbox: { href: "/inbox/private-report" },
            },
          },
          taskId: "private-task",
          appView: "inbox",
        }),
      ],
    };
    const repo = new FakeRepository(initial);
    const service = new BrowserTabsService(repo);

    const reset = service.reset();

    expect(reset.windows).toEqual([
      expect.objectContaining({ id: "win-1", activeTabId: expect.any(String) }),
    ]);
    expect(reset.tabs).toEqual([
      expect.objectContaining({
        windowId: "win-1",
        href: NEW_TAB_HREF,
        viewState: null,
        taskId: null,
        appView: null,
      }),
    ]);
    expect(repo.saved).toEqual(reset);
  });
});

describe("BrowserTabsService window-id healing", () => {
  // A mirror seeded before a schema repair, or another window's since-closed
  // id, must not append into a window that does not exist.
  it("opens into the primary window when the given id is unknown", () => {
    const repo = new FakeRepository({ windows: [], tabs: [] });
    const service = new BrowserTabsService(repo);
    const primaryId = service.getPrimaryWindowId();

    const snapshot = service.openTab({
      windowId: "stale-window-id",
      href: "/inbox",
      viewState: null,
      dashboardId: null,
      taskId: null,
      channelId: null,
      tabId: "tab-open",
    });

    expect(snapshot.tabs.find((t) => t.id === "tab-open")?.windowId).toBe(
      primaryId,
    );
  });

  // Without dedup there is nothing to absorb a replayed open, so the minted id
  // is what keeps it from appending a second copy.
  it("is idempotent on a replayed open", () => {
    const repo = new FakeRepository({ windows: [], tabs: [] });
    const service = new BrowserTabsService(repo);
    const open = () =>
      service.openTab({
        windowId: service.getPrimaryWindowId(),
        href: "/inbox",
        viewState: null,
        dashboardId: null,
        taskId: null,
        channelId: null,
        tabId: "tab-open",
      });

    open();
    const snapshot = open();

    expect(snapshot.tabs.filter((t) => t.id === "tab-open")).toHaveLength(1);
  });
});
