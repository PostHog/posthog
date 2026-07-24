import {
  canvasShareUrl,
  errorTrackingIssueUrl,
  parseShareLink,
} from "@posthog/ui/utils/posthogLinks";
import { describe, expect, it, vi } from "vitest";

vi.mock("@posthog/ui/utils/urls", () => ({
  getPostHogUrl: (path: string) => `https://us.posthog.com${path}`,
}));

describe("canvasShareUrl", () => {
  it("builds an https /code/canvas link with encoded ids", () => {
    expect(canvasShareUrl("chan/1", "dash 2", "us")).toBe(
      "https://us.posthog.com/code/canvas/chan%2F1/dash%202",
    );
  });
});

describe("parseShareLink", () => {
  it.each([
    [
      "canvas link",
      "https://us.posthog.com/code/canvas/chan1/dash1",
      { kind: "canvas", channelId: "chan1", dashboardId: "dash1" },
    ],
    [
      "canvas link with encoded ids",
      "https://us.posthog.com/code/canvas/chan%2F1/dash%202",
      { kind: "canvas", channelId: "chan/1", dashboardId: "dash 2" },
    ],
    [
      "channel link on the eu host",
      "https://eu.posthog.com/code/channel/chan1",
      { kind: "channel", channelId: "chan1" },
    ],
    [
      "channel thread link",
      "https://us.posthog.com/code/channel/chan1/tasks/task1",
      { kind: "channel", channelId: "chan1", taskId: "task1" },
    ],
  ])("parses a %s", (_label, href, expected) => {
    expect(parseShareLink(href)).toEqual(expected);
  });

  it.each([
    ["a non-PostHog host", "https://evil.com/code/canvas/chan1/dash1"],
    [
      "an unrelated PostHog path",
      "https://us.posthog.com/project/2/dashboard/1",
    ],
    [
      "a canvas link missing the dashboard id",
      "https://us.posthog.com/code/canvas/chan1",
    ],
    [
      "a channel thread link with a malformed tail",
      "https://us.posthog.com/code/channel/chan1/foo/task1",
    ],
    ["a malformed url", "not a url"],
  ])("returns null for %s", (_label, href) => {
    expect(parseShareLink(href)).toBeNull();
  });
});

describe("errorTrackingIssueUrl", () => {
  it("links to the issue when no fingerprint is provided", () => {
    expect(
      errorTrackingIssueUrl("issue id/with?chars", {
        projectId: 123,
        cloudRegion: "us",
      }),
    ).toBe(
      "https://us.posthog.com/project/123/error_tracking/issue%20id%2Fwith%3Fchars",
    );
  });

  it("includes a fingerprint query parameter for merged issue redirects", () => {
    expect(
      errorTrackingIssueUrl("old-issue-id", {
        projectId: 123,
        cloudRegion: "us",
        fingerprint: "fp/value with spaces&eq=1",
      }),
    ).toBe(
      "https://us.posthog.com/project/123/error_tracking/old-issue-id?fingerprint=fp%2Fvalue%20with%20spaces%26eq%3D1",
    );
  });
});
