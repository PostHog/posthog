import type { TabsSnapshot } from "@posthog/shared";
import type { BrowserTabsClient } from "@posthog/ui/features/browser-tabs/browserTabsClient";
import { stateStorage } from "@posthog/ui/shell/rendererStorage";

export const ONBOARDING_TAB_HREF = "/onboarding-landing";

const DISMISSED = "dismissed";
const LEGACY_OPENED = "opened";
const storageKey = (identity: string): string =>
  `first-run-onboarding-tab:${identity}`;

type OnboardingBrowserTabsClient = Pick<
  BrowserTabsClient,
  "getPrimaryWindowId" | "getSnapshot" | "openTab"
>;
type BrowserTab = TabsSnapshot["tabs"][number];

const pendingEnsures = new Map<string, Promise<void>>();

export function isOnboardingTab(
  tab: Pick<BrowserTab, "appView" | "href">,
): boolean {
  return tab.appView === "onboarding" || tab.href === ONBOARDING_TAB_HREF;
}

async function ensureTab(
  identity: string,
  client: OnboardingBrowserTabsClient,
): Promise<void> {
  const key = storageKey(identity);
  const [savedState, snapshot] = await Promise.all([
    stateStorage.getItem(key),
    client.getSnapshot(),
  ]);
  const tabIsOpen = snapshot.tabs.some(isOnboardingTab);

  if (savedState === DISMISSED) return;
  if (savedState === LEGACY_OPENED) {
    if (tabIsOpen) {
      await stateStorage.removeItem(key);
    } else {
      await stateStorage.setItem(key, DISMISSED);
    }
    return;
  }
  if (tabIsOpen) return;

  const windowId = await client.getPrimaryWindowId();
  await client.openTab({
    windowId,
    tabId: crypto.randomUUID(),
    href: ONBOARDING_TAB_HREF,
    viewState: { title: "Onboarding" },
    dashboardId: null,
    taskId: null,
    channelId: null,
    channelSection: null,
    appView: "onboarding",
    activate: false,
  });
}

export function ensureOnboardingTab(
  identity: string,
  client: OnboardingBrowserTabsClient,
): Promise<void> {
  const pending = pendingEnsures.get(identity);
  if (pending) return pending;

  const operation = ensureTab(identity, client).finally(() => {
    if (pendingEnsures.get(identity) === operation) {
      pendingEnsures.delete(identity);
    }
  });
  pendingEnsures.set(identity, operation);
  return operation;
}

export async function markOnboardingTabClosed(
  identity: string,
  tabs: readonly Pick<BrowserTab, "appView" | "href">[],
): Promise<void> {
  if (!tabs.some(isOnboardingTab)) return;
  await stateStorage.setItem(storageKey(identity), DISMISSED);
}

export async function restoreOnboardingTab(identity: string): Promise<void> {
  await stateStorage.removeItem(storageKey(identity));
}
