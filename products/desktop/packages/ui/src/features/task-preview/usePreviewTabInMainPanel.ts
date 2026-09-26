import { DEFAULT_PANEL_IDS } from "@posthog/core/panels/panelConstants";
import { createPreviewTabId } from "@posthog/core/panels/panelStoreHelpers";
import { findTabInTree } from "@posthog/core/panels/panelTree";
import { usePanelLayoutStore } from "@posthog/ui/features/panels/panelLayoutStore";

export function usePreviewTabInMainPanel(
  taskId: string,
  runId: string,
  port: number,
): boolean {
  return usePanelLayoutStore((state) => {
    const layout = state.taskLayouts[taskId];
    if (!layout) return false;
    const found = findTabInTree(
      layout.panelTree,
      createPreviewTabId(runId, port),
    );
    return found?.panelId === DEFAULT_PANEL_IDS.MAIN_PANEL;
  });
}
