import type { ITaskBrowserHost } from "@posthog/platform/task-browser";
import { usePanelLayoutStore } from "@posthog/ui/features/panels/panelLayoutStore";
import { afterEach, describe, expect, it, vi } from "vitest";
import { TaskBrowserContribution } from "./taskBrowser.contribution";

function layoutWithBrowserTabs(browserIds: string[]) {
  return {
    "task-1": {
      panelTree: {
        type: "leaf",
        id: "main",
        content: {
          id: "main",
          activeTabId: "chat",
          tabs: browserIds.map((browserId) => ({
            id: `browser-${browserId}`,
            label: "Browser",
            data: { type: "browser", browserId, url: "" },
          })),
        },
      },
      openFiles: [],
      recentFiles: [],
      draggingTabId: null,
      draggingTabPanelId: null,
      focusedPanelId: null,
    },
  } as never;
}

describe("TaskBrowserContribution", () => {
  afterEach(() => {
    usePanelLayoutStore.setState({ taskLayouts: {} });
  });

  it("tells the host to forget a browser tab only when the user closes it", () => {
    const forgetTab = vi.fn(async () => undefined);
    const noop = () => () => undefined;
    const host = {
      onOpenRequest: noop,
      onCloseRequest: noop,
      onPermissionRequest: noop,
      onPermissionSettled: noop,
      forgetTab,
    } as unknown as ITaskBrowserHost;
    usePanelLayoutStore.setState({
      taskLayouts: layoutWithBrowserTabs(["kept", "closed"]),
    });
    const contribution = new TaskBrowserContribution(host);
    contribution.start();

    usePanelLayoutStore.setState({
      taskLayouts: layoutWithBrowserTabs(["kept"]),
    });

    expect(forgetTab).toHaveBeenCalledTimes(1);
    expect(forgetTab).toHaveBeenCalledWith("closed");
    contribution.stop();
  });
});
