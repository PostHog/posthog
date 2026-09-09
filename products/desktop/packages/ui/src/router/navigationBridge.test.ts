import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  getRouterOrNull: vi.fn(),
}));

vi.mock("./routerRef", () => ({
  getRouterOrNull: mocks.getRouterOrNull,
}));

import {
  navigateToChannelNewTask,
  navigateToChannelReportDetail,
  navigateToInboxDismissedDetail,
  navigateToInboxPullRequestDetail,
  navigateToInboxReportDetail,
  navigateToNewTask,
  navigateToReport,
} from "./navigationBridge";
import {
  reportNavigationState,
  reportSourceHref,
  validReportSource,
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
  const location = {
    href: "/settings/agents?filter=custom",
    pathname: "/settings/agents",
    state: { tabId: "agents-tab" },
  };

  beforeEach(() => {
    vi.clearAllMocks();
    mocks.getRouterOrNull.mockReturnValue({
      navigate,
      state: { location },
      history: { location, replace },
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
    const { to, params, state } = navigate.mock.calls[0][0];
    expect(to).toBe("/reports/$reportId");
    expect(params).toEqual({ reportId: "report-1" });
    expect(state(location.state)).toEqual({
      tabId: "agents-tab",
      reportSourceHref: location.href,
    });
  });

  it("opens external deep links without inheriting a source", () => {
    navigateToReport("report-1", { preserveSource: false });
    expect(
      navigate.mock.calls[0][0].state({
        tabId: "agents-tab",
        reportSourceHref: "/activity",
      }),
    ).toEqual({ tabId: "agents-tab" });
  });

  it("keeps the original source when opening another report", () => {
    mocks.getRouterOrNull.mockReturnValue({
      state: {
        location: {
          href: "/reports/first",
          pathname: "/reports/first",
          state: { reportSourceHref: "/activity?task=task-1" },
        },
      },
    });
    expect(reportNavigationState({ tabId: "report-tab" })).toEqual({
      tabId: "report-tab",
      reportSourceHref: "/activity?task=task-1",
    });
  });

  it("records triage selection on the source history entry", () => {
    navigateToInboxReportDetail("report-1", { returnToTriage: true });
    expect(replace).toHaveBeenCalledWith(location.href, {
      ...location.state,
      inboxTriageOrigin: { reportId: "report-1" },
    });
  });

  it.each([
    "/settings/agents",
    "/activity?task=task-1",
    "/spaces/space-1",
    "/inbox/reports",
    "/tasks/task-1",
  ])("accepts internal origin %s", (source) =>
    expect(validReportSource(source)).toBe(source),
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
    "/spaces/space-1/reports/first",
    "/activity\n",
  ])("rejects unsafe or recursive origin %s", (source) =>
    expect(validReportSource(source)).toBeUndefined(),
  );

  it("ignores leftover origin state outside the report route", () => {
    expect(
      reportSourceHref({
        pathname: "/activity",
        state: { reportSourceHref: "/settings/agents" },
      }),
    ).toBeUndefined();
  });
});
