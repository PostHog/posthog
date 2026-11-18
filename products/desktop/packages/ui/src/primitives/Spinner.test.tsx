import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Spinner } from "./Spinner";

describe("Spinner", () => {
  it.each([
    ["xs", "size-2.5"],
    ["sm", "size-3"],
    ["md", "size-4"],
    ["lg", "size-6"],
  ] as const)("sizes the icon for %s with %s", (size, sizeClass) => {
    render(<Spinner size={size} />);
    const status = screen.getByRole("status", { name: "Loading" });
    expect(status).toHaveClass("animate-spin", "motion-reduce:animate-none");
    expect(status.querySelector("svg")).toHaveClass(sizeClass);
  });

  it("leaves the icon unclassed by default so quill containers can size it", () => {
    render(<Spinner />);
    const icon = screen.getByRole("status").querySelector("svg");
    expect(icon).toHaveAttribute("width", "16");
    expect(icon?.getAttribute("class")).not.toMatch(/size-/);
  });

  it("holds still when spinning is off", () => {
    render(<Spinner spinning={false} label="Connecting" />);
    expect(screen.getByRole("status", { name: "Connecting" })).not.toHaveClass(
      "animate-spin",
    );
  });
});
