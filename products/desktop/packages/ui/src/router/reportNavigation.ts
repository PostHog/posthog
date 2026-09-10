import {
  resolveSettingsCategory,
  SETTINGS_PAGE_LABELS,
  type SettingsCategory,
} from "@posthog/ui/features/settings/types";
import { type HistoryState, useRouterState } from "@tanstack/react-router";
import { getRouterOrNull } from "./routerRef";

export interface NavigationSource {
  href: string;
  path: string;
  label: string;
  settingsCategory: SettingsCategory | null;
  agentSkillName: string | null;
  spaceId: string | null;
  feedId: string | null;
}

interface SourceLocation {
  pathname: string;
  href: string;
  search?: unknown;
}

export function isReportPath(pathname: string): boolean {
  return /^\/reports\/[^/]+\/?$/.test(pathname);
}

export function reportIdFromHref(href: string | null): string | null {
  if (!href) return null;
  const pathname = href.split(/[?#]/)[0];
  return isReportPath(pathname) ? (pathname.split("/")[2] ?? null) : null;
}

function isSettingsPath(pathname: string): boolean {
  return /^\/settings(\/|$)/.test(pathname);
}

export function validSourceHref(href: unknown): string | undefined {
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
    /^\/inbox\/(reports|pulls|runs|dismissed)\/[^/]+\/?$/.test(pathname) ||
    /^\/spaces\/[^/]+\/reports\/[^/]+\/?$/.test(pathname)
  ) {
    return undefined;
  }
  return href;
}

const SOURCE_LABELS: readonly (readonly [RegExp, string])[] = [
  [/^\/inbox\/agents(\/|$)/, "Agents"],
  [/^\/inbox(\/|$)/, "Self-driving"],
  [/^\/activity(\/|$)/, "Activity"],
  [/^\/loops(\/|$)/, "Loops"],
  [/^\/canvases(\/|$)/, "Canvases"],
  [/^\/command-center(\/|$)/, "Command center"],
  [/^\/feeds(\/|$)/, "Feeds"],
  [/^\/skills(\/|$)/, "Skills"],
  [/^\/mcp-servers(\/|$)/, "MCP servers"],
  [/^\/spaces(\/|$)/, "Spaces"],
];

function sourceLabel(path: string, category: SettingsCategory | null): string {
  if (category) return SETTINGS_PAGE_LABELS[category];
  if (path === "/") return "Home";
  return SOURCE_LABELS.find(([pattern]) => pattern.test(path))?.[1] ?? "Back";
}

export function resolveNavigationSource(
  href: string | undefined,
): NavigationSource | null {
  const valid = validSourceHref(href);
  if (!valid) return null;
  const path = valid.split(/[?#]/)[0];
  const category = resolveSettingsCategory(
    path.match(/^\/settings\/([^/]+)/)?.[1] ?? "",
  );
  return {
    href: valid,
    path,
    label: sourceLabel(path, category),
    settingsCategory: category,
    agentSkillName: valid.match(/[?&]agent=([^&#]+)/)?.[1] ?? null,
    spaceId: path.match(/^\/spaces\/([^/]+)/)?.[1] ?? null,
    feedId: path.match(/^\/feeds\/([^/]+)/)?.[1] ?? null,
  };
}

export function sourceHrefFromSearch(
  location: SourceLocation,
): string | undefined {
  return validSourceHref(
    (location.search as { from?: unknown } | undefined)?.from,
  );
}

export function reportSourceHrefFromLocation(
  location: SourceLocation,
): string | undefined {
  return isReportPath(location.pathname)
    ? sourceHrefFromSearch(location)
    : undefined;
}

function currentSourceHref(
  carriesOwnSource: (pathname: string) => boolean,
): string | undefined {
  const location = getRouterOrNull()?.state?.location;
  if (!location) return undefined;
  return carriesOwnSource(location.pathname)
    ? sourceHrefFromSearch(location)
    : validSourceHref(location.href);
}

export function navigationSourceHref(): string | undefined {
  return currentSourceHref(isReportPath);
}

export function settingsSourceHref(): string | undefined {
  return currentSourceHref(isSettingsPath);
}

export function useReportSourceHref(): string | undefined {
  return useRouterState({
    select: (state) => reportSourceHrefFromLocation(state.location),
  });
}

/**
 * A settings route, or a report opened from one (the report route hosts the
 * settings portal). Everything the root pairs with that portal — inert chrome,
 * banner suppression, settings-only shortcuts — reads this, so the report
 * route gets the same pairing a plain settings route has.
 */
export function useSettingsOverlay(): boolean {
  return useRouterState({
    select: (state) =>
      state.matches.some((match) => match.routeId.includes("/settings/")) ||
      reportSourceHrefFromLocation(state.location)?.startsWith("/settings/") ===
        true,
  });
}

export function reportNavigationState(previous: HistoryState): HistoryState {
  return {
    ...(previous.tabId ? { tabId: previous.tabId } : {}),
    ...(previous.inboxTriageOrigin
      ? { inboxTriageOrigin: previous.inboxTriageOrigin }
      : {}),
  };
}
