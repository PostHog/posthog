import { usePanelLayoutStore } from "@posthog/ui/features/panels/panelLayoutStore";
import type { PanelNode, Tab } from "@posthog/ui/features/panels/panelTypes";

function browserTabs(node: PanelNode): Tab[] {
  if (node.type === "leaf") {
    return node.content.tabs.filter((tab) => tab.data.type === "browser");
  }
  return node.children.flatMap(browserTabs);
}

function originOf(url: string): string | null {
  try {
    return new URL(url).origin;
  } catch {
    return null;
  }
}

export function openBrowserPage(
  taskId: string,
  page: { url: string; label: string },
): void {
  const store = usePanelLayoutStore.getState();
  const layout = store.getLayout(taskId);
  const tabs = layout ? browserTabs(layout.panelTree) : [];
  const origin = originOf(page.url);
  const existing =
    tabs.find(
      (tab) => tab.data.type === "browser" && originOf(tab.data.url) === origin,
    ) ?? tabs[0];
  if (existing?.data.type === "browser") {
    store.openBrowserTab(taskId, {
      browserId: existing.data.browserId,
      url: existing.data.url,
      label: existing.label,
    });
    return;
  }
  store.openBrowserTab(taskId, {
    browserId: crypto.randomUUID(),
    url: page.url,
    label: page.label,
  });
}
