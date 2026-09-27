import type {
  TaskBrowserCloseRequest,
  TaskBrowserOpenRequest,
} from "@posthog/platform/task-browser";
import { usePanelLayoutStore } from "@posthog/ui/features/panels/panelLayoutStore";
import type { PanelNode } from "@posthog/ui/features/panels/panelTypes";
import { browserTabLabel, originOf } from "./browserAddress";
import { useBrowserNavigationStore } from "./browserNavigationStore";

type BrowserTabRef = { browserId: string; url: string; label: string };

function browserTabs(node: PanelNode): BrowserTabRef[] {
  if (node.type === "group") return node.children.flatMap(browserTabs);
  return node.content.tabs.flatMap((tab) =>
    tab.data.type === "browser"
      ? [{ browserId: tab.data.browserId, url: tab.data.url, label: tab.label }]
      : [],
  );
}

export function openAgentBrowserTab(request: TaskBrowserOpenRequest): void {
  usePanelLayoutStore.getState().openBrowserTab(request.taskId, {
    browserId: request.browserId,
    url: request.url,
    label: browserTabLabel(request.url),
  });
}

export function closeAgentBrowserTab(request: TaskBrowserCloseRequest): void {
  usePanelLayoutStore
    .getState()
    .closeBrowserTab(request.taskId, request.browserId);
}

export function openBrowserPage(
  taskId: string,
  page: { url: string; label: string },
): void {
  const store = usePanelLayoutStore.getState();
  const layout = store.getLayout(taskId);
  const origin = originOf(page.url);
  const existing = layout
    ? browserTabs(layout.panelTree).find(
        (tab) => origin !== null && originOf(tab.url) === origin,
      )
    : undefined;
  if (existing) {
    useBrowserNavigationStore
      .getState()
      .requestNavigation(existing.browserId, page.url);
    store.openBrowserTab(taskId, existing);
    return;
  }
  store.openBrowserTab(taskId, {
    browserId: crypto.randomUUID(),
    url: page.url,
    label: page.label,
  });
}
