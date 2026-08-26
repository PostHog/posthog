import {
  navigateToChannel,
  navigateToChannelDashboard,
  navigateToChannelTask,
} from "@posthog/ui/router/navigationBridge";
import {
  parseShareLink,
  type ShareLinkTarget,
} from "@posthog/ui/utils/posthogLinks";
import { getPostHogUrl } from "@posthog/ui/utils/urls";

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

/**
 * The canvas or channel an href points at, but only when the link belongs to the
 * PostHog instance the user is signed in to. Canvas and channel ids are
 * per-instance, so a link from another region names rows that don't exist here —
 * opening it in-app would land on an empty canvas. Those stay browser links.
 */
export function parseLocalShareLink(
  href: string | undefined | null,
): ShareLinkTarget | null {
  if (!href) return null;
  const base = getPostHogUrl("/");
  if (!base) return null;
  try {
    if (new URL(href).origin !== new URL(base).origin) return null;
  } catch {
    return null;
  }
  return parseShareLink(href);
}

interface ShareLinkClickEvent {
  preventDefault: () => void;
  defaultPrevented?: boolean;
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
  if (event.defaultPrevented || isModifiedClick(event)) return false;
  const target = parseLocalShareLink(href);
  if (!target) return false;
  event.preventDefault();
  navigateToShareTarget(target);
  return true;
}

/**
 * Open canvas and channel links in the app instead of the browser, wherever the
 * link is rendered — agent prose, thread messages, an inbox report, a canvas's
 * own HTML. Electron hands any anchor it doesn't recognise to `shell.openExternal`,
 * so a surface that doesn't call {@link handleShareLinkClick} itself sends the
 * user out to the web page for a canvas the app can show directly.
 *
 * Capture phase on the document, so it runs before React's own handlers; those
 * then see `defaultPrevented` and stand down rather than navigating twice.
 * Links to another instance and modified clicks fall through untouched, keeping
 * "open in a new window" working.
 */
export function interceptShareLinkClicks(root: Document): () => void {
  const onClick = (event: MouseEvent): void => {
    const node = event.target;
    if (!(node instanceof Element)) return;
    const anchor = node.closest("a[href]");
    if (!(anchor instanceof HTMLAnchorElement)) return;
    handleShareLinkClick(anchor.href, event);
  };
  root.addEventListener("click", onClick, true);
  return () => root.removeEventListener("click", onClick, true);
}
