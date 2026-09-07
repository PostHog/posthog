import type { BrowserTabsClient } from "@posthog/ui/features/browser-tabs/browserTabsClient";
import { stateStorage } from "@posthog/ui/shell/rendererStorage";

const storageKey = (identity: string): string =>
  `first-run-onboarding-tab:${identity}`;

type FirstRunBrowserTabsClient = Pick<
  BrowserTabsClient,
  "getPrimaryWindowId" | "openTab"
>;

const pendingOpens = new Map<string, Promise<void>>();

async function openTab(
  identity: string,
  client: FirstRunBrowserTabsClient,
): Promise<void> {
  const key = storageKey(identity);
  if (await stateStorage.getItem(key)) return;

  const windowId = await client.getPrimaryWindowId();
  await client.openTab({
    windowId,
    tabId: crypto.randomUUID(),
    href: "/onboarding-landing",
    viewState: { title: "Onboarding" },
    dashboardId: null,
    taskId: null,
    channelId: null,
    channelSection: null,
    appView: "onboarding",
    activate: false,
  });
  await stateStorage.setItem(key, "opened");
}

export function openFirstRunOnboardingTab(
  identity: string,
  client: FirstRunBrowserTabsClient,
): Promise<void> {
  const pending = pendingOpens.get(identity);
  if (pending) return pending;

  const operation = openTab(identity, client).finally(() => {
    if (pendingOpens.get(identity) === operation) {
      pendingOpens.delete(identity);
    }
  });
  pendingOpens.set(identity, operation);
  return operation;
}
