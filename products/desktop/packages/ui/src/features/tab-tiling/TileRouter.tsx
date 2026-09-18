import { type BrowserTab, setTabTarget } from "@posthog/shared";
import {
  applyLocalTransform,
  persistTabTarget,
} from "@posthog/ui/features/browser-tabs/tabsSync";
import {
  createMemoryHistory,
  createRouter,
  RouterProvider,
  useRouter,
} from "@tanstack/react-router";
import { useEffect, useState } from "react";

function recordTabHref(tab: BrowserTab, href: string): void {
  const target = {
    tabId: tab.id,
    href,
    viewState: tab.viewState ?? null,
    dashboardId: tab.dashboardId,
    taskId: tab.taskId,
    channelId: tab.channelId,
    channelSection: tab.channelSection,
    appView: tab.appView,
  };
  applyLocalTransform((s) => setTabTarget(s, { ...target, now: Date.now }));
  persistTabTarget(target);
}

export function TileRouter({ tab, href }: { tab: BrowserTab; href: string }) {
  const outer = useRouter();
  const [inner] = useState(() =>
    createRouter({
      ...outer.options,
      history: createMemoryHistory({ initialEntries: [href] }),
      scrollRestoration: false,
    }),
  );

  useEffect(() => {
    return inner.subscribe("onResolved", ({ toLocation }) => {
      if (toLocation.href !== tab.href) recordTabHref(tab, toLocation.href);
    });
  }, [inner, tab]);

  return <RouterProvider router={inner} />;
}
