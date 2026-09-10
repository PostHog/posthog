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
  it("draws the working ring larger than the column it sits in", () => {
    render(
      <>
        <TaskStatusDot dot={working} />
        <TaskStatusDot dot={idle} />
      </>,
    );

    const column = screen.getByRole("img", { name: "All caught up" }).style
      .width;
    const mark = screen.getByRole("img", { name: "Loading" });
    const ring = mark.firstElementChild as HTMLElement;

    expect(mark.style.width).toBe(column);
    expect(Number.parseFloat(ring.style.width)).toBeGreaterThan(
      Number.parseFloat(column),
    );
  });
});
