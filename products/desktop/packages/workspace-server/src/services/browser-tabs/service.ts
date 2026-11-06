import {
  type BrowserWindow,
  closeTab,
  closeTabs,
  DEFAULT_TAB_HREF,
  ensureWindowHasTab,
  openTab,
  resetTabs,
  setTabOrder,
  setTabTarget,
  setWindowActiveTab,
  type TabLocation,
  type TabsSnapshot,
  type TabTarget,
  TypedEventEmitter,
} from "@posthog/shared";
import { inject, injectable } from "inversify";
import { BROWSER_TABS_REPOSITORY } from "../../db/identifiers";
import type { IBrowserTabsRepository } from "../../db/repositories/browser-tabs-repository";
import { BrowserTabsEvent, type BrowserTabsEvents } from "./schemas";

const makeId = () => crypto.randomUUID();
const now = () => Date.now();

export interface IBrowserTabsService {
  getSnapshot(): TabsSnapshot;
  getPrimaryWindowId(): string;
  reset(): TabsSnapshot;
  openTab(
    input: TabTarget &
      TabLocation & {
        windowId: string;
        channelId: string | null;
        channelSection?: string | null;
        appView?: string | null;
        tabId?: string;
      },
  ): TabsSnapshot;
  setTabTarget(
    input: TabTarget &
      TabLocation & {
        tabId: string;
        channelId: string | null;
        channelSection?: string | null;
        appView?: string | null;
        activate?: boolean;
      },
  ): TabsSnapshot;
  close(tabId: string, newTabId: string): TabsSnapshot;
  closeMany(
    tabIds: string[],
    newTabId: string,
    focusTabId?: string | null,
  ): TabsSnapshot;
  setOrder(input: { windowId: string; tabIds: string[] }): TabsSnapshot;
  setActiveTab(input: { windowId: string; tabId: string | null }): TabsSnapshot;
  snapshotChangeEvents(
    signal: AbortSignal | undefined,
  ): AsyncIterable<TabsSnapshot>;
}

/**
 * Authoritative, single-instance owner of the Channels browser-tab strips.
 * Lives in the shared main process so every renderer window reads and mutates
 * one source of truth; changes fan out to all windows via the snapshot-change
 * subscription. Durable state is persisted through the repository; the
 * back/forward action timeline is per-renderer and lives in the UI, not here.
 */
@injectable()
export class BrowserTabsService
  extends TypedEventEmitter<BrowserTabsEvents>
  implements IBrowserTabsService
{
  private snapshot: TabsSnapshot;

  constructor(
    @inject(BROWSER_TABS_REPOSITORY)
    private readonly repo: IBrowserTabsRepository,
  ) {
    super();
    this.setMaxListeners(0);
    const loaded = this.repo.load();
    const seeded = this.ensureAtLeastOneTab(this.ensurePrimaryWindow(loaded));
    if (seeded !== loaded) this.repo.save(seeded);
    this.snapshot = seeded;
  }

  /** Guarantee a primary window exists so the first open has somewhere to land. */
  private ensurePrimaryWindow(snapshot: TabsSnapshot): TabsSnapshot {
    if (snapshot.windows.some((w) => w.isPrimary)) return snapshot;
    const primary: BrowserWindow = {
      id: makeId(),
      isPrimary: true,
      bounds: null,
      activeTabId: null,
    };
    return { ...snapshot, windows: [primary, ...snapshot.windows] };
  }

  /** Keep a primary tab available when persisted state is empty or damaged. */
  private ensureAtLeastOneTab(snapshot: TabsSnapshot): TabsSnapshot {
    const primary = snapshot.windows.find((window) => window.isPrimary);
    if (!primary) return snapshot;
    return ensureWindowHasTab(snapshot, {
      windowId: primary.id,
      href: DEFAULT_TAB_HREF,
      makeId,
      now,
    });
  }

  /** Creation targets heal a stale window id (a mirror seeded before a schema
   * repair, or another window's since-closed id) to the primary window rather
   * than appending into a window that doesn't exist. Deliberately creation-only:
   * a desynced mirror's reorder (`setOrder`) or focus (`setActiveTab`) carries
   * stale TAB ids too, so retargeting those at the primary window would apply
   * wrong state — the shared transforms no-op safely instead, and the snapshot
   * reconcile heals the mirror. Creating a tab is window-independent intent. */
  private resolveWindowId(windowId: string): string {
    return this.snapshot.windows.some((w) => w.id === windowId)
      ? windowId
      : this.getPrimaryWindowId();
  }

  getSnapshot(): TabsSnapshot {
    return this.snapshot;
  }

  /** Id of the primary window — the default target before multi-window. */
  getPrimaryWindowId(): string {
    const primary = this.snapshot.windows.find((w) => w.isPrimary);
    if (!primary) throw new Error("browser-tabs: no primary window");
    return primary.id;
  }

  reset(): TabsSnapshot {
    return this.commit(
      resetTabs(this.snapshot, { href: DEFAULT_TAB_HREF, makeId, now }),
    );
  }

  openTab(
    input: TabTarget &
      TabLocation & {
        windowId: string;
        channelId: string | null;
        channelSection?: string | null;
        appView?: string | null;
        tabId?: string;
      },
  ): TabsSnapshot {
    const providedId = input.tabId;
    // Idempotent on the renderer-minted id. There is no dedup to fall back on
    // (opening never focuses an existing tab), so a replayed call would
    // otherwise append a second copy.
    if (providedId && this.snapshot.tabs.some((t) => t.id === providedId)) {
      return this.snapshot;
    }
    const { snapshot } = openTab(this.snapshot, {
      ...input,
      windowId: this.resolveWindowId(input.windowId),
      makeId: providedId ? () => providedId : makeId,
      now,
    });
    return this.commit(snapshot);
  }

  setTabTarget(
    input: TabTarget &
      TabLocation & {
        tabId: string;
        channelId: string | null;
        channelSection?: string | null;
        appView?: string | null;
      },
  ): TabsSnapshot {
    return this.commit(setTabTarget(this.snapshot, { ...input, now }));
  }

  close(tabId: string, newTabId: string): TabsSnapshot {
    const { snapshot } = closeTab(this.snapshot, tabId, {
      href: DEFAULT_TAB_HREF,
      makeId: () => newTabId,
      now,
    });
    return this.commit(snapshot);
  }

  closeMany(
    tabIds: string[],
    newTabId: string,
    focusTabId?: string | null,
  ): TabsSnapshot {
    return this.commit(
      closeTabs(
        this.snapshot,
        tabIds,
        { href: DEFAULT_TAB_HREF, makeId: () => newTabId, now },
        focusTabId,
      ),
    );
  }

  setOrder(input: { windowId: string; tabIds: string[] }): TabsSnapshot {
    return this.commit(
      setTabOrder(this.snapshot, input.windowId, input.tabIds),
    );
  }

  setActiveTab(input: {
    windowId: string;
    tabId: string | null;
  }): TabsSnapshot {
    // Validated: a tabId that doesn't exist in the window (a stale history tag
    // replayed after the tab closed) is ignored rather than persisted as a
    // dangling activeTabId — that dangle makes every later navigation look like
    // "no active tab" and silently open new tabs.
    const next = setWindowActiveTab(this.snapshot, input.windowId, input.tabId);
    if (next === this.snapshot) return this.snapshot;
    return this.commit(next);
  }

  snapshotChangeEvents(
    signal: AbortSignal | undefined,
  ): AsyncIterable<TabsSnapshot> {
    return this.toIterable(BrowserTabsEvent.SnapshotChange, { signal });
  }

  private commit(next: TabsSnapshot): TabsSnapshot {
    this.snapshot = next;
    this.repo.save(next);
    this.emit(BrowserTabsEvent.SnapshotChange, next);
    return next;
  }
}
