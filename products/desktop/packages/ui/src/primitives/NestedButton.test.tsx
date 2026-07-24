import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { NestedButton } from "./NestedButton";

describe("NestedButton", () => {
  it("renders an accessible button", () => {
    render(<NestedButton onActivate={() => {}}>x</NestedButton>);
    expect(screen.getByRole("button")).toBeTruthy();
  });

  it("calls onActivate on click without bubbling to the parent", async () => {
    const onActivate = vi.fn();
    const onParentClick = vi.fn();
    render(
      // biome-ignore lint/a11y/useKeyWithClickEvents: test-only wrapper
      // biome-ignore lint/a11y/noStaticElementInteractions: test-only wrapper
      <div onClick={onParentClick}>
        <NestedButton onActivate={onActivate}>x</NestedButton>
      </div>,
    );
    await userEvent.click(screen.getByRole("button"));
    expect(onActivate).toHaveBeenCalledTimes(1);
    expect(onParentClick).not.toHaveBeenCalled();
  });

  it.each(["{Enter}", " "])("activates with the %s key", async (key) => {
    const onActivate = vi.fn();
    render(<NestedButton onActivate={onActivate}>x</NestedButton>);
    screen.getByRole("button").focus();
    await userEvent.keyboard(key);
    expect(onActivate).toHaveBeenCalledTimes(1);
  });
});
