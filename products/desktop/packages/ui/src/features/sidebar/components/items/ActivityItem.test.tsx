import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

vi.mock("@posthog/ui/features/canvas/hooks/useTaskActivity", () => ({
  useTaskActivity: () => ({ unreadCount: 2 }),
}));
vi.mock("@posthog/ui/features/canvas/components/ActivityHoverCard", () => ({
  ActivityHoverCard: () => <div>Recent activity card</div>,
}));

import { ActivityItem } from "./ActivityItem";

describe("ActivityItem", () => {
  it("navigates without opening the hover card or adding a second tab stop", async () => {
    const onClick = vi.fn();
    const user = userEvent.setup();
    const { container } = render(
      <ActivityItem isActive={false} onClick={onClick} />,
    );

    expect(container.querySelectorAll("button")).toHaveLength(1);
    await user.click(screen.getByRole("button", { name: /Activity/ }));

    expect(onClick).toHaveBeenCalledOnce();
    expect(screen.queryByText("Recent activity card")).not.toBeInTheDocument();
  });

  it("keeps the active Activity row enabled without mounting a popover", () => {
    const { container } = render(<ActivityItem isActive onClick={vi.fn()} />);

    expect(screen.getByRole("button", { name: /Activity/ })).toBeEnabled();
    expect(container.querySelector("[aria-haspopup]")).not.toBeInTheDocument();
  });
});
