import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { InlineEditInput, TaskItem } from "./TaskItem";

describe("InlineEditInput", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("waits for the desktop window to regain focus before focusing rename", async () => {
    vi.spyOn(document, "hasFocus").mockReturnValue(false);

    render(
      <InlineEditInput
        depth={0}
        icon={null}
        label="Original title"
        isActive={false}
        onSubmit={vi.fn()}
        onCancel={vi.fn()}
      />,
    );

    const input = screen.getByRole("textbox");
    expect(input).not.toHaveFocus();

    fireEvent.focus(window);

    await waitFor(() => expect(input).toHaveFocus());
    expect(input).toHaveProperty("selectionStart", 0);
    expect(input).toHaveProperty("selectionEnd", "Original title".length);
  });
});

describe("TaskItem", () => {
  it.each([
    ["archive", { isArchiving: true }, "Archiving"],
    ["filing", { isFiling: true }, "Filing"],
  ] as const)(
    "renders inert %s progress instead of edit or pull request actions",
    (_operation, progress, label) => {
      const onClick = vi.fn();
      const onDoubleClick = vi.fn();
      const onContextMenu = vi.fn();
      const { container } = render(
        <TaskItem
          taskId="task-1"
          label="Archive me"
          isActive={false}
          {...progress}
          isEditing
          prUrl="https://github.com/PostHog/posthog/pull/123"
          onClick={onClick}
          onDoubleClick={onDoubleClick}
          onContextMenu={onContextMenu}
        />,
      );

      const row = screen.getByText("Archive me").closest("button");
      expect(row).toHaveAttribute("aria-busy", "true");
      expect(row).toHaveAttribute("aria-disabled", "true");
      expect(screen.getByText(label)).toHaveClass("sr-only");
      expect(container.querySelector("[aria-hidden='true']")).not.toBeNull();
      expect(screen.queryByRole("textbox")).toBeNull();
      expect(screen.queryByLabelText("Open pull request #123")).toBeNull();

      if (row) {
        fireEvent.click(row);
        fireEvent.doubleClick(row);
        fireEvent.contextMenu(row);
      }
      expect(onClick).not.toHaveBeenCalled();
      expect(onDoubleClick).not.toHaveBeenCalled();
      expect(onContextMenu).not.toHaveBeenCalled();
    },
  );
});
