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

describe("TaskStatusDot", () => {
  it("uses the braille spinner without changing the status column width", () => {
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
    expect(mark.querySelector(".ph-dots-frame")).toHaveTextContent("⠋");
    expect(mark.querySelector("svg")).not.toBeInTheDocument();
  });
});
