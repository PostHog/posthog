import type { BrowserTab } from "@posthog/shared";
import { writeBackgroundTabTarget } from "@posthog/ui/features/browser-tabs/imperativeTabNavigation";
import {
  createMemoryHistory,
  createRouter,
  RouterProvider,
  useRouter,
} from "@tanstack/react-router";
import { useEffect, useState } from "react";

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
      if (toLocation.href === tab.href) return;
      writeBackgroundTabTarget(tab, {
        href: toLocation.href,
        dashboardId: tab.dashboardId,
        taskId: tab.taskId,
        channelId: tab.channelId,
        channelSection: tab.channelSection,
        appView: tab.appView,
      });
    });
  }, [inner, tab]);

  return <RouterProvider router={inner} />;
}
