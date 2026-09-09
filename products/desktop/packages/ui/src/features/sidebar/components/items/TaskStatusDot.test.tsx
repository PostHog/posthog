import { TaskStatusDot } from "@posthog/ui/features/sidebar/components/items/TaskStatusDot";
import type { TaskDot } from "@posthog/ui/features/sidebar/components/items/taskStatusVocabulary";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

const working: TaskDot = {
  tone: "yellow",
  style: "solid",
  pulse: false,
  spinner: true,
  label: "Loading",
};

const idle: TaskDot = {
  tone: "gray",
  style: "hollow",
  pulse: false,
  label: "All caught up",
};

const blocked: TaskDot = {
  tone: "blue",
  style: "solid",
  pulse: false,
  label: "Needs your input",
};

describe("TaskStatusDot", () => {
  it("uses a standard spinner without changing the status column width", () => {
    render(
      <>
        <TaskStatusDot dot={working} />
        <TaskStatusDot dot={idle} />
      </>,
    );

    const column = screen.getByRole("img", { name: "All caught up" }).style
      .width;
    const mark = screen.getByRole("img", { name: "Loading" });

    expect(mark.style.width).toBe(column);
    expect(mark.firstElementChild).toHaveClass("animate-spin");
    expect(mark.querySelector("svg")).toBeInTheDocument();
  });

  it("grows a row's trigger past the dot without moving the mark", () => {
    // Separate containers, so each dot's siblings are only its own.
    render(<TaskStatusDot dot={idle} />);
    render(<TaskStatusDot dot={blocked} hitArea="row" />);

    const bare = screen.getByRole("img", { name: "All caught up" });
    const mark = screen.getByRole("img", { name: "Needs your input" });

    // The dot keeps the box it had, so the row's leading column doesn't shift.
    expect(mark.style.width).toBe(bare.style.width);
    // What grew is the trigger around it, and only for a row.
    expect(mark.parentElement).toHaveClass("relative");
    expect(mark.parentElement?.querySelector(".absolute")).toHaveClass(
      "-inset-2",
    );
    expect(bare.parentElement?.querySelector(".absolute")).toBeNull();
  });
});
