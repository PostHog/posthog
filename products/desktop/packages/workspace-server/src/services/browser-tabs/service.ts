import {
  type BrowserWindow,
  closeTab,
  closeTabs,
  newBlankTab,
  openOrFocusTab,
  setTabOrder,
  setTabTarget,
  setWindowActiveTab,
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
  openOrFocus(
    input: TabTarget & {
      windowId: string;
      channelId: string | null;
      channelSection?: string | null;
      appView?: string | null;
      tabId?: string;
    },
  ): TabsSnapshot;
  newBlankTab(input: { windowId: string; tabId?: string }): TabsSnapshot;
  setTabTarget(
    input: TabTarget & {
      tabId: string;
      channelId: string | null;
      channelSection?: string | null;
      appView?: string | null;
    },
  ): TabsSnapshot;
  close(tabId: string): TabsSnapshot;
  closeMany(tabIds: string[], focusTabId?: string | null): TabsSnapshot;
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

  /** The strip must never boot empty: seed a blank tab when none survived. */
  private ensureAtLeastOneTab(snapshot: TabsSnapshot): TabsSnapshot {
    if (snapshot.tabs.length > 0) return snapshot;
    const primary = snapshot.windows.find((w) => w.isPrimary);
    if (!primary) return snapshot;
    return newBlankTab(snapshot, { windowId: primary.id, makeId, now })
      .snapshot;
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

  openOrFocus(
    input: TabTarget & {
      windowId: string;
      channelId: string | null;
      channelSection?: string | null;
      appView?: string | null;
      tabId?: string;
    },
  ): TabsSnapshot {
    // Honor a renderer-minted id so the caller's optimistic apply and this
    // persisted state agree on the id. Dedup-by-identity still applies first,
    // so a replay of the same open focuses the existing tab.
    const providedId = input.tabId;
    const { snapshot } = openOrFocusTab(this.snapshot, {
      ...input,
      windowId: this.resolveWindowId(input.windowId),
      makeId: providedId ? () => providedId : makeId,
      now,
    });
    return this.commit(snapshot);
  }

  newBlankTab(input: { windowId: string; tabId?: string }): TabsSnapshot {
    const providedId = input.tabId;
    // Idempotent on the renderer-minted id: a replay of the same call (blank
    // tabs have no identity to dedup on) must not append a second tab.
    if (providedId && this.snapshot.tabs.some((t) => t.id === providedId)) {
      return this.snapshot;
    }
    const { snapshot } = newBlankTab(this.snapshot, {
      windowId: this.resolveWindowId(input.windowId),
      makeId: providedId ? () => providedId : makeId,
      now,
    });
    return this.commit(snapshot);
  }

  setTabTarget(
    input: TabTarget & {
      tabId: string;
      channelId: string | null;
      channelSection?: string | null;
      appView?: string | null;
    },
  ): TabsSnapshot {
    return this.commit(setTabTarget(this.snapshot, { ...input, now }));
  }

  close(tabId: string): TabsSnapshot {
    const { snapshot } = closeTab(this.snapshot, tabId);
    return this.commit(snapshot);
  }

  closeMany(tabIds: string[], focusTabId?: string | null): TabsSnapshot {
    return this.commit(closeTabs(this.snapshot, tabIds, focusTabId));
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
