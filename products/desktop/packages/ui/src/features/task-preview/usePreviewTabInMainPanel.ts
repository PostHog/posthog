import { DEFAULT_PANEL_IDS } from "@posthog/core/panels/panelConstants";
import {
  createPreviewTabId,
  getLeafPanel,
} from "@posthog/core/panels/panelStoreHelpers";
import { findTabInTree } from "@posthog/core/panels/panelTree";
import { usePanelLayoutStore } from "@posthog/ui/features/panels/panelLayoutStore";

export function useTabInMainPanel(taskId: string, tabId: string): boolean {
  return usePanelLayoutStore((state) => {
    const layout = state.taskLayouts[taskId];
    if (!layout) return false;
    return (
      findTabInTree(layout.panelTree, tabId)?.panelId ===
      DEFAULT_PANEL_IDS.MAIN_PANEL
    );
  });
}

export function usePreviewTabInMainPanel(
  taskId: string,
  runId: string,
  port: number,
): boolean {
  return useTabInMainPanel(taskId, createPreviewTabId(runId, port));
}

export function useTabIsActive(taskId: string, tabId: string): boolean {
  return usePanelLayoutStore((state) => {
    const layout = state.taskLayouts[taskId];
    if (!layout) return false;
    const found = findTabInTree(layout.panelTree, tabId);
    if (!found) return false;
    const panel = getLeafPanel(layout.panelTree, found.panelId);
    return panel?.content.activeTabId === tabId;
  });
}
