import { render, screen } from "@testing-library/react";
import type { ComponentProps } from "react";
import { describe, expect, it, vi } from "vitest";
import { ChannelContextChip } from "./ChannelContextChip";
import { channelContextChipProps } from "./channelContext";

function renderChip(props: ComponentProps<typeof ChannelContextChip>): void {
  render(<ChannelContextChip {...props} />);
}

describe("ChannelContextChip", () => {
  it.each([
    [
      "resolved context-layer page",
      "spaces/engineering.md",
      { label: "engineering.md", removable: false },
    ],
    [
      "legacy CONTEXT.md fallback",
      undefined,
      { label: "CONTEXT.md", removable: true },
    ],
  ] as const)(
    "labels the chip for a %s",
    (_case, channelContextPath, expected) => {
      expect(channelContextChipProps(channelContextPath)).toEqual(expected);
    },
  );

  it("keeps legacy CONTEXT.md removable", () => {
    renderChip({
      label: "CONTEXT.md",
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

  it("names a wiki page and offers no remove control", () => {
    renderChip({ label: "engineering.md", channelName: "engineering" });

    expect(screen.getByText("engineering.md")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^Remove/ })).toBeNull();
  });
});
