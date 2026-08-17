import { ChatCircleIcon, PulseIcon } from "@phosphor-icons/react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { type PanelSide, PanelSideSwitcher } from "./PanelSideSwitcher";

type Side = "timeline" | "comments";

const SIDES: readonly PanelSide<Side>[] = [
  { key: "timeline", label: "Timeline", Icon: PulseIcon },
  { key: "comments", label: "Comments", Icon: ChatCircleIcon },
];

describe("PanelSideSwitcher", () => {
  it.each<[string, Side | null, string, Side | null]>([
    ["closes the side already open", "timeline", "Timeline", null],
    ["opens another side", "timeline", "Comments", "comments"],
    ["opens from nothing open", null, "Timeline", "timeline"],
  ])("%s", async (_case, active, clicked, expected) => {
    const onSelect = vi.fn();
    render(
      <PanelSideSwitcher sides={SIDES} active={active} onSelect={onSelect} />,
    );

    await userEvent.click(screen.getByRole("button", { name: clicked }));

    expect(onSelect).toHaveBeenCalledWith(expected);
  });

  it("marks only the active side as selected", () => {
    render(
      <PanelSideSwitcher sides={SIDES} active="comments" onSelect={vi.fn()} />,
    );

    expect(screen.getByRole("button", { name: "Comments" })).toHaveAttribute(
      "data-selected",
    );
    expect(
      screen.getByRole("button", { name: "Timeline" }),
    ).not.toHaveAttribute("data-selected");
  });
});
