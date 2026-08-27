import { Theme } from "@radix-ui/themes";
import { render, screen } from "@testing-library/react";
import type { ComponentProps } from "react";
import { describe, expect, it, vi } from "vitest";
import { ChannelContextChip } from "./ChannelContextChip";

function renderChip(props: ComponentProps<typeof ChannelContextChip>): void {
  render(
    <Theme>
      <ChannelContextChip {...props} />
    </Theme>,
  );
}

describe("ChannelContextChip", () => {
  it("shows the context layer as an always-connected session resource", () => {
    renderChip({ source: "context-layer" });

    expect(screen.getByText("Context layer")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /remove/i })).toBeNull();
  });

  it("keeps legacy CONTEXT.md removable", () => {
    renderChip({
      source: "legacy",
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
