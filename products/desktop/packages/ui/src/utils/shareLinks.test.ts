import { handleShareLinkClick } from "@posthog/ui/utils/shareLinks";
import { beforeEach, describe, expect, it, vi } from "vitest";

const navigateToChannel = vi.fn();
const navigateToChannelDashboard = vi.fn();
const navigateToChannelTask = vi.fn();

vi.mock("@posthog/ui/router/navigationBridge", () => ({
  navigateToChannel: (...args: unknown[]) => navigateToChannel(...args),
  navigateToChannelDashboard: (...args: unknown[]) =>
    navigateToChannelDashboard(...args),
  navigateToChannelTask: (...args: unknown[]) => navigateToChannelTask(...args),
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
