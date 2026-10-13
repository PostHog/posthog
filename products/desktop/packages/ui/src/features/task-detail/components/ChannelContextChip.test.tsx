import { render, screen } from "@testing-library/react";
import type { ComponentProps } from "react";
import { describe, expect, it, vi } from "vitest";
import { ChannelContextChip } from "./ChannelContextChip";
import { shouldShowChannelContextChip } from "./channelContext";

function renderChip(props: ComponentProps<typeof ChannelContextChip>): void {
  render(<ChannelContextChip {...props} />);
}

describe("ChannelContextChip", () => {
  it.each([
    ["resolved context-layer page", true, "/spaces/engineering.md", false],
    ["legacy CONTEXT.md fallback", true, undefined, true],
    ["dismissed legacy context", false, undefined, false],
  ] as const)(
    "shows the chip for %s: %s",
    (_case, includeChannelContext, channelContextPath, expected) => {
      expect(
        shouldShowChannelContextChip(includeChannelContext, channelContextPath),
      ).toBe(expected);
    },
  );

  it("keeps legacy CONTEXT.md removable", () => {
    renderChip({
      channelName: "engineering",
      onRemove: vi.fn(),
    });

    expect(screen.getByText("CONTEXT.md")).toBeInTheDocument();
    expect(
      screen.getByRole("button", {
        name: "Remove #engineering CONTEXT.md",
      }),
    ).toBeInTheDocument();
  });
});
