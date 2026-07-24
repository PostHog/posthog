import {
  navigateToChannel,
  navigateToChannelDashboard,
  navigateToChannelTask,
} from "@posthog/ui/router/navigationBridge";
import {
  parseShareLink,
  type ShareLinkTarget,
} from "@posthog/ui/utils/posthogLinks";

export function navigateToShareTarget(target: ShareLinkTarget): void {
  switch (target.kind) {
    case "canvas":
      navigateToChannelDashboard(target.channelId, target.dashboardId);
      break;
    case "channel":
      if (target.taskId) {
        navigateToChannelTask(target.channelId, target.taskId);
      } else {
        navigateToChannel(target.channelId);
      }
      break;
  }
}

interface ShareLinkClickEvent {
  preventDefault: () => void;
  metaKey?: boolean;
  ctrlKey?: boolean;
  shiftKey?: boolean;
  altKey?: boolean;
  button?: number;
}

function isModifiedClick(event: ShareLinkClickEvent): boolean {
  return Boolean(
    event.metaKey ||
      event.ctrlKey ||
      event.shiftKey ||
      event.altKey ||
      (event.button != null && event.button !== 0),
  );
}

export function handleShareLinkClick(
  href: string | undefined,
  event: ShareLinkClickEvent,
): boolean {
  if (!href || isModifiedClick(event)) return false;
  const target = parseShareLink(href);
  if (!target) return false;
  event.preventDefault();
  navigateToShareTarget(target);
  return true;
}
