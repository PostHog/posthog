import { navigateBrowserTab } from "@posthog/ui/features/browser-tabs/imperativeTabNavigation";
import { openTaskInput } from "@posthog/ui/router/useOpenTask";

export function restoreTaskInputTab(
  tabId: string | null,
  spaceId?: string,
): void {
  navigateBrowserTab(
    tabId,
    {
      href: spaceId ? `/spaces/${spaceId}/new` : "/new",
      title: "New task",
      channelId: spaceId,
    },
    () => openTaskInput(spaceId ? { channelId: spaceId } : { unscoped: true }),
  );
}
