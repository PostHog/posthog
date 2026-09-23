import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { StepList } from "./StepList";

const openExternalUrl = vi.fn();

vi.mock("@posthog/ui/shell/openExternal", () => ({
  openExternalUrl: (url: string) => openExternalUrl(url),
}));

describe("StepList", () => {
  beforeEach(() => {
    openExternalUrl.mockClear();
  });

  it("opens a URL detail in the system browser", async () => {
    render(
      <StepList
        steps={[
          {
            key: "pr",
            label: "Opened pull request",
            status: "completed",
            detail: "https://github.com/PostHog/posthog/pull/123",
          },
        ]}
      />,
    );

    const link = screen.getByRole("button", {
      name: "Open github.com/PostHog/posthog/pull/123",
    });
    expect(link).toHaveTextContent("github.com/PostHog/posthog/pull/123");

    await userEvent.click(link);

    expect(openExternalUrl).toHaveBeenCalledWith(
      "https://github.com/PostHog/posthog/pull/123",
    );
  });

  it.each([
    ["plain text", "Cloned PostHog/posthog"],
    ["a non-web scheme", "file:///tmp/report.txt"],
  ])("renders %s as inert text", (_case, detail) => {
    render(
      <StepList
        steps={[
          {
            key: "repo",
            label: "Repository ready",
            detail,
            status: "completed",
          },
        ]}
      />,
    );

    expect(screen.getByText(detail)).toBeInTheDocument();
    expect(screen.queryByRole("button")).toBeNull();
  });
});
