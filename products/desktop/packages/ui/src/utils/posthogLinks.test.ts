import {
  canvasShareUrl,
  colonOffsetToSeconds,
  errorTrackingIssueUrl,
  inboxReportUrl,
  parseShareLink,
  sessionRecordingUrl,
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

describe("inboxReportUrl", () => {
  it("builds the browser-accessible report URL", () => {
    expect(
      inboxReportUrl("report/id", { projectId: 123, cloudRegion: "us" }),
    ).toBe("https://us.posthog.com/project/123/inbox/report%2Fid");
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

describe("colonOffsetToSeconds", () => {
  it.each([
    ["MM:SS", "01:47", 107],
    ["HH:MM:SS", "1:02:03", 3723],
    ["zero-padded minutes", "10:00", 600],
  ])("parses %s", (_label, offset, expected) => {
    expect(colonOffsetToSeconds(offset)).toBe(expected);
  });

  it.each([
    ["a bare number", "47"],
    ["too many parts", "1:2:3:4"],
    ["a non-numeric part", "ab:cd"],
    ["a negative part", "-1:00"],
    ["an empty segment", "1::2"],
    ["a hex literal", "0x10:00"],
    ["scientific notation", "1e308:00"],
    ["padded whitespace", " 1 : 2 "],
    ["seconds of 60", "1:60"],
    ["minutes of 60 in HH:MM:SS", "1:60:00"],
  ])("returns null for %s", (_label, offset) => {
    expect(colonOffsetToSeconds(offset)).toBeNull();
  });
});

describe("sessionRecordingUrl", () => {
  it("links to the recording without a seek offset", () => {
    expect(
      sessionRecordingUrl("session-id-1", undefined, {
        projectId: 123,
        cloudRegion: "us",
      }),
    ).toBe("https://us.posthog.com/project/123/replay/session-id-1");
  });

  it("includes a ?t= seek offset when provided", () => {
    expect(
      sessionRecordingUrl(
        "session-id-1",
        { secondsOffsetFromStart: 107 },
        { projectId: 123, cloudRegion: "us" },
      ),
    ).toBe("https://us.posthog.com/project/123/replay/session-id-1?t=107");
  });

  it("omits the offset when it is explicitly null", () => {
    expect(
      sessionRecordingUrl(
        "session-id-1",
        { secondsOffsetFromStart: null },
        { projectId: 123, cloudRegion: "us" },
      ),
    ).toBe("https://us.posthog.com/project/123/replay/session-id-1");
  });
});
