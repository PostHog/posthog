import {
  handleShareLinkClick,
  interceptShareLinkClicks,
} from "@posthog/ui/utils/shareLinks";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const navigateToChannel = vi.fn();
const navigateToChannelDashboard = vi.fn();
const navigateToChannelTask = vi.fn();

vi.mock("@posthog/ui/router/navigationBridge", () => ({
  navigateToChannel: (...args: unknown[]) => navigateToChannel(...args),
  navigateToChannelDashboard: (...args: unknown[]) =>
    navigateToChannelDashboard(...args),
  navigateToChannelTask: (...args: unknown[]) => navigateToChannelTask(...args),
}));

vi.mock("@posthog/ui/utils/urls", () => ({
  getPostHogUrl: (path: string) => `https://us.posthog.com${path}`,
}));

beforeEach(() => {
  vi.clearAllMocks();
});

describe("handleShareLinkClick", () => {
  it("navigates in-app and cancels the default open for a share link", () => {
    const event = { preventDefault: vi.fn() };

    const handled = handleShareLinkClick(
      "https://us.posthog.com/code/canvas/chan1/dash1",
      event,
    );

    expect(handled).toBe(true);
    expect(event.preventDefault).toHaveBeenCalledOnce();
    expect(navigateToChannelDashboard).toHaveBeenCalledWith("chan1", "dash1");
  });

  it("routes a channel thread link to the task navigator", () => {
    const event = { preventDefault: vi.fn() };

    handleShareLinkClick(
      "https://us.posthog.com/code/channel/chan1/tasks/task1",
      event,
    );

    expect(navigateToChannelTask).toHaveBeenCalledWith("chan1", "task1");
  });

  it.each([
    ["meta", { metaKey: true }],
    ["ctrl", { ctrlKey: true }],
    ["shift", { shiftKey: true }],
    ["a middle button", { button: 1 }],
  ])(
    "leaves a %s-modified click to open in a new tab/window",
    (_label, modifier) => {
      const event = { preventDefault: vi.fn(), ...modifier };

      const handled = handleShareLinkClick(
        "https://us.posthog.com/code/canvas/chan1/dash1",
        event,
      );

      expect(handled).toBe(false);
      expect(event.preventDefault).not.toHaveBeenCalled();
      expect(navigateToChannelDashboard).not.toHaveBeenCalled();
    },
  );

  it("leaves a canvas on another PostHog instance to the browser", () => {
    const event = { preventDefault: vi.fn() };

    const handled = handleShareLinkClick(
      "https://eu.posthog.com/code/canvas/chan1/dash1",
      event,
    );

    expect(handled).toBe(false);
    expect(event.preventDefault).not.toHaveBeenCalled();
    expect(navigateToChannelDashboard).not.toHaveBeenCalled();
  });

  it("stands down when something already handled the click", () => {
    const event = { preventDefault: vi.fn(), defaultPrevented: true };

    const handled = handleShareLinkClick(
      "https://us.posthog.com/code/canvas/chan1/dash1",
      event,
    );

    expect(handled).toBe(false);
    expect(navigateToChannelDashboard).not.toHaveBeenCalled();
  });

  it("leaves an external link alone", () => {
    const event = { preventDefault: vi.fn() };

    const handled = handleShareLinkClick("https://example.com/docs", event);

    expect(handled).toBe(false);
    expect(event.preventDefault).not.toHaveBeenCalled();
    expect(navigateToChannel).not.toHaveBeenCalled();
    expect(navigateToChannelDashboard).not.toHaveBeenCalled();
    expect(navigateToChannelTask).not.toHaveBeenCalled();
  });

  it("returns false for a missing href", () => {
    const event = { preventDefault: vi.fn() };

    expect(handleShareLinkClick(undefined, event)).toBe(false);
    expect(event.preventDefault).not.toHaveBeenCalled();
  });
});

describe("interceptShareLinkClicks", () => {
  let uninstall: () => void;

  function clickAnchor(href: string): boolean {
    const anchor = document.createElement("a");
    anchor.href = href;
    anchor.target = "_blank";
    const label = document.createElement("span");
    label.textContent = "link";
    anchor.append(label);
    document.body.append(anchor);
    // Clicking the inner span, not the anchor, also covers the `closest` walk
    // from whatever element the user actually hit.
    return label.dispatchEvent(
      new MouseEvent("click", { bubbles: true, cancelable: true }),
    );
  }

  beforeEach(() => {
    uninstall = interceptShareLinkClicks(document);
  });

  afterEach(() => {
    uninstall();
    document.body.replaceChildren();
  });

  it("opens a canvas link the app rendered without asking the browser", () => {
    const notCancelled = clickAnchor(
      "https://us.posthog.com/code/canvas/chan1/dash1",
    );

    expect(notCancelled).toBe(false);
    expect(navigateToChannelDashboard).toHaveBeenCalledWith("chan1", "dash1");
  });

  it("lets an external link through to the browser", () => {
    const notCancelled = clickAnchor("https://example.com/docs");

    expect(notCancelled).toBe(true);
    expect(navigateToChannelDashboard).not.toHaveBeenCalled();
  });

  it("stops intercepting once uninstalled", () => {
    uninstall();

    const notCancelled = clickAnchor(
      "https://us.posthog.com/code/canvas/chan1/dash1",
    );

    expect(notCancelled).toBe(true);
    expect(navigateToChannelDashboard).not.toHaveBeenCalled();
  });
});
