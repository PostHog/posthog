import { Theme } from "@radix-ui/themes";
import { render, screen } from "@testing-library/react";
import type { ComponentProps } from "react";
import { describe, expect, it, vi } from "vitest";
import {
  ChannelContextChip,
  shouldShowChannelContextChip,
} from "./ChannelContextChip";

function renderChip(props: ComponentProps<typeof ChannelContextChip>): void {
  render(
    <Theme>
      <ChannelContextChip {...props} />
    </Theme>,
  );
}

describe("ChannelContextChip", () => {
  it.each([
    ["context layer flag", true, true, false],
    ["legacy CONTEXT.md", true, false, true],
    ["dismissed legacy context", false, false, false],
  ] as const)(
    "shows the chip for %s: %s",
    (_case, includeChannelContext, contextLayerEnabled, expected) => {
      expect(
        shouldShowChannelContextChip(
          includeChannelContext,
          contextLayerEnabled,
        ),
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
