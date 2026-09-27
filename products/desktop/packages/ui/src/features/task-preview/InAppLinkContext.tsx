import { useServiceOptional } from "@posthog/di/react";
import { TASK_BROWSER_HOST } from "@posthog/platform/task-browser";
import { usePanelLayoutStore } from "@posthog/ui/features/panels/panelLayoutStore";
import {
  createContext,
  type MouseEvent,
  type ReactNode,
  useCallback,
  useContext,
} from "react";
import { browserTabLabel } from "./browserAddress";

type OpenInApp = (url: string) => boolean;

const InAppLinkContext = createContext<OpenInApp | null>(null);

export function TaskInAppLinks({
  taskId,
  children,
}: {
  taskId: string;
  children: ReactNode;
}) {
  const host = useServiceOptional(TASK_BROWSER_HOST);
  const openBrowserTab = usePanelLayoutStore((state) => state.openBrowserTab);
  const open = useCallback(
    (url: string) => {
      let parsed: URL;
      try {
        parsed = new URL(url);
      } catch {
        return false;
      }
      if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
        return false;
      }
      openBrowserTab(taskId, {
        browserId: crypto.randomUUID(),
        url: parsed.toString(),
        label: browserTabLabel(parsed.toString()),
      });
      return true;
    },
    [openBrowserTab, taskId],
  );
  if (!host) return children;
  return (
    <InAppLinkContext.Provider value={open}>
      {children}
    </InAppLinkContext.Provider>
  );
}

export function useInAppLinkHandler() {
  const openInApp = useContext(InAppLinkContext);
  return (event: MouseEvent, href: string | undefined): boolean => {
    if (!openInApp || !href) return false;
    if (
      event.metaKey ||
      event.ctrlKey ||
      event.shiftKey ||
      event.button !== 0
    ) {
      return false;
    }
    if (!openInApp(href)) return false;
    event.preventDefault();
    return true;
  };
}
