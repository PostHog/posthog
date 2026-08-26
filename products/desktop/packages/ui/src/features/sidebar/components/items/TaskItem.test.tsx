import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { InlineEditInput } from "./TaskItem";

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
