import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  getRouterOrNull: vi.fn(),
}));

vi.mock("./routerRef", () => ({
  getRouterOrNull: mocks.getRouterOrNull,
}));

import {
  leaveSettingsRoute,
  navigateToChannelNewTask,
  navigateToChannelReportDetail,
  navigateToInboxDismissedDetail,
  navigateToInboxPullRequestDetail,
  navigateToInboxReportDetail,
  navigateToNewTask,
  navigateToReport,
  navigateToSettings,
} from "./navigationBridge";
import {
  reportSourceHrefFromLocation,
  resolveNavigationSource,
  validSourceHref,
} from "./reportNavigation";

type StateUpdater = (prev: Record<string, unknown>) => Record<string, unknown>;

// The composer screens key their draft session on `state.tabId`
// (getTaskInputSessionId) and remount on that key. A new-task entry born
// without the tag gets stamped by the tab strip a beat later, which flips the
// key and remounts the composer AFTER it consumed the one-shot prefill — the
// prompt handed to openTaskInput (a posthog-code://new?prompt= deep link, a
// show_actions compose button) silently vanished. These pin the entry to be
// born already tagged with the tab it stays in.
describe("new-task navigation carries the tab tag", () => {
  const navigate = vi.fn();

  beforeEach(() => {
    vi.clearAllMocks();
    mocks.getRouterOrNull.mockReturnValue({ navigate });
  });

  it("navigateToNewTask preserves the current entry's tabId", () => {
    navigateToNewTask();

    expect(navigate).toHaveBeenCalledTimes(1);
    const { to, state } = navigate.mock.calls[0][0];
    expect(to).toBe("/new");
    expect((state as StateUpdater)({ tabId: "tab-1" })).toEqual({
      tabId: "tab-1",
    });
  });

  it("navigateToChannelNewTask preserves the current entry's tabId", () => {
    navigateToChannelNewTask("chan-1");

    expect(navigate).toHaveBeenCalledTimes(1);
    const call = navigate.mock.calls[0][0];
    expect(call.to).toBe("/spaces/$channelId/new");
    expect(call.params).toEqual({ channelId: "chan-1" });
    expect((call.state as StateUpdater)({ tabId: "tab-9" })).toEqual({
      tabId: "tab-9",
    });
  });

  // Route-scoped state (loopListOrigin, inboxBackOrigin) describes the entry
  // being left; only the tab tag may survive onto the new-task entry.
  it("carries only the tab tag, not other state keys", () => {
    navigateToNewTask();

    const { state } = navigate.mock.calls[0][0];
    expect(
      (state as StateUpdater)({ tabId: "tab-1", loopListOrigin: "loops" }),
    ).toEqual({ tabId: "tab-1" });
  });

  it("leaves an untagged entry untagged", () => {
    navigateToNewTask();

    const { state } = navigate.mock.calls[0][0];
    expect((state as StateUpdater)({})).toEqual({});
  });

  it("degrades to a no-op when the router is not mounted", () => {
    mocks.getRouterOrNull.mockReturnValue(null);

    expect(() => navigateToNewTask()).not.toThrow();
    expect(() => navigateToChannelNewTask("chan-1")).not.toThrow();
    expect(navigate).not.toHaveBeenCalled();
  });
});

describe("canonical report navigation", () => {
  const navigate = vi.fn();
  const replace = vi.fn();
  const push = vi.fn();
  const location = {
    href: "/settings/agents?filter=custom",
    pathname: "/settings/agents",
    search: {},
    state: { tabId: "agents-tab" },
  };

  beforeEach(() => {
    vi.clearAllMocks();
    mocks.getRouterOrNull.mockReturnValue({
      navigate,
      state: { location },
      history: { location, replace, push },
    });
  });

  it.each([
    navigateToReport,
    navigateToInboxReportDetail,
    navigateToInboxPullRequestDetail,
    navigateToInboxDismissedDetail,
    (reportId: string) =>
      navigateToChannelReportDetail("owning-space", reportId),
  ])("opens the canonical path and keeps the source", (open) => {
    open("report-1");
    const { to, params, search, state } = navigate.mock.calls[0][0];
    expect(to).toBe("/reports/$reportId");
    expect(params).toEqual({ reportId: "report-1" });
    expect(search).toEqual({ from: location.href });
    expect(state(location.state)).toEqual({ tabId: "agents-tab" });
  });

  it("opens external deep links without inheriting a source", () => {
    navigateToReport("report-1", { preserveSource: false });
    expect(navigate.mock.calls[0][0].search).toEqual({});
  });

  it("keeps the original source when opening another report", () => {
    mocks.getRouterOrNull.mockReturnValue({
      navigate,
      state: {
        location: {
          href: "/reports/first",
          pathname: "/reports/first",
          search: { from: "/activity?task=task-1" },
          state: { tabId: "report-tab" },
        },
      },
    });
    navigateToReport("report-2");
    expect(navigate.mock.calls[0][0].search).toEqual({
      from: "/activity?task=task-1",
    });
  });

  it("records triage selection on the source history entry", () => {
    navigateToInboxReportDetail("report-1", { returnToTriage: true });
    expect(replace).toHaveBeenCalledWith(location.href, {
      ...location.state,
      inboxTriageOrigin: { reportId: "report-1" },
    });
  });

  it("carries the triage origin onto the report entry", () => {
    navigateToInboxReportDetail("report-1", { returnToTriage: true });
    const { state } = navigate.mock.calls[0][0];
    expect(
      state({ tabId: "agents-tab", inboxTriageOrigin: { reportId: "r" } }),
    ).toEqual({ tabId: "agents-tab", inboxTriageOrigin: { reportId: "r" } });
  });

  it.each([
    "/settings/agents",
    "/activity?task=task-1",
    "/spaces/space-1",
    "/inbox/reports",
    "/tasks/task-1",
  ])("accepts internal origin %s", (source) =>
    expect(validSourceHref(source)).toBe(source),
  );

  it.each([
    undefined,
    null,
    {},
    "https://example.com",
    "//example.com",
    "/\\example.com",
    "/reports/first",
    "/inbox/pulls/first",
    "/inbox/runs/first",
    "/spaces/space-1/reports/first",
    "/activity\n",
  ])("rejects unsafe or recursive origin %s", (source) =>
    expect(validSourceHref(source)).toBeUndefined(),
  );

  it("ignores an origin outside the report route", () => {
    expect(
      reportSourceHrefFromLocation({
        pathname: "/activity",
        href: "/activity",
        search: { from: "/settings/agents" },
      }),
    ).toBeUndefined();
  });

  it.each([
    ["/settings/agents", "Agents"],
    ["/settings/claude-code", "Harness"],
    ["/inbox/reports", "Self-driving"],
    ["/inbox/agents", "Agents"],
    ["/activity?task=task-1", "Activity"],
    ["/feeds/github", "Feeds"],
    ["/", "Home"],
    ["/tasks/task-1", "Back"],
  ])("labels the origin %s as %s", (href, label) =>
    expect(resolveNavigationSource(href)?.label).toBe(label),
  );

  it("names the space and feed an origin points at", () => {
    expect(resolveNavigationSource("/spaces/space-1")?.spaceId).toBe("space-1");
    expect(resolveNavigationSource("/feeds/github")?.feedId).toBe("github");
  });
});

describe("leaving the settings route", () => {
  const navigate = vi.fn();
  const push = vi.fn();

  const mountOn = (search: Record<string, unknown>) => {
    const location = {
      href: "/settings/agents",
      pathname: "/settings/agents",
      search,
      state: { tabId: "agents-tab" },
    };
    mocks.getRouterOrNull.mockReturnValue({
      navigate,
      state: { location },
      history: { location, push },
    });
  };

  beforeEach(() => vi.clearAllMocks());

  it("returns to the route that opened settings", () => {
    mountOn({ from: "/spaces/space-1" });
    leaveSettingsRoute();
    expect(push).toHaveBeenCalledWith("/spaces/space-1", {
      tabId: "agents-tab",
    });
    expect(navigate).not.toHaveBeenCalled();
  });

  it("falls back to the app when settings was reached directly", () => {
    mountOn({});
    leaveSettingsRoute();
    expect(push).not.toHaveBeenCalled();
    expect(navigate.mock.calls[0][0].to).toBe("/new");
  });

  it("keeps the source across a category switch", () => {
    mountOn({ from: "/spaces/space-1" });
    navigateToSettings("skills", { replace: true });
    const { to, params, search, replace } = navigate.mock.calls[0][0];
    expect(to).toBe("/settings/$category");
    expect(params).toEqual({ category: "skills" });
    expect(search).toEqual({ from: "/spaces/space-1" });
    expect(replace).toBe(true);
  });
});
