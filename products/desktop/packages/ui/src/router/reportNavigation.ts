import type { HistoryState } from "@tanstack/react-router";
import { getRouterOrNull } from "./routerRef";

declare module "@tanstack/history" {
  interface HistoryState {
    reportSourceHref?: string;
  }
}

export function isReportPath(pathname: string): boolean {
  return /^\/reports\/[^/]+\/?$/.test(pathname);
}

export function validReportSource(href: unknown): string | undefined {
  if (
    typeof href !== "string" ||
    !href.startsWith("/") ||
    href.startsWith("//") ||
    href.includes("\\") ||
    Array.from(href).some((character) => character.charCodeAt(0) <= 32)
  ) {
    return undefined;
  }
  const pathname = href.split(/[?#]/)[0];
  if (
    isReportPath(pathname) ||
    /^\/inbox\/(reports|pulls|dismissed)\/[^/]+\/?$/.test(pathname) ||
    /^\/spaces\/[^/]+\/reports\/[^/]+\/?$/.test(pathname)
  ) {
    return undefined;
  }
  return href;
}

export function reportSourceHref(location: {
  pathname: string;
  state: HistoryState;
}): string | undefined {
  return isReportPath(location.pathname)
    ? validReportSource(location.state.reportSourceHref)
    : undefined;
}

export function reportNavigationState(previous: HistoryState): HistoryState {
  const location = getRouterOrNull()?.state?.location;
  const source = location
    ? isReportPath(location.pathname)
      ? reportSourceHref(location)
      : validReportSource(location.href)
    : undefined;
  return {
    ...(previous.tabId ? { tabId: previous.tabId } : {}),
    ...(source ? { reportSourceHref: source } : {}),
    ...(previous.inboxTriageOrigin
      ? { inboxTriageOrigin: previous.inboxTriageOrigin }
      : {}),
  };
}

export function legacyReportNavigationState(
  previous: HistoryState,
): HistoryState {
  const source =
    validReportSource(previous.reportSourceHref) ??
    validReportSource(getRouterOrNull()?.state.resolvedLocation?.href);
  return { ...previous, reportSourceHref: source };
}
