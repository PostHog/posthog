import { TaskStatusDot } from "@posthog/ui/features/sidebar/components/items/TaskStatusDot";
import type { TaskDot } from "@posthog/ui/features/sidebar/components/items/taskStatusVocabulary";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

const working: TaskDot = {
  tone: "yellow",
  style: "solid",
  pulse: false,
  spinner: true,
  label: "Working",
};

describe("TaskStatusDot", () => {
  // The two halves of the same constraint, and the pair is the point: the ring
  // has to outgrow the dot's box to read as a ring at all, and it has to leave
  // that box's width alone or every working row's label steps right.
  it("draws the working ring larger than the column it occupies", () => {
    render(<TaskStatusDot dot={working} />);

    const mark = screen.getByRole("img", { name: "Working" });
    const ring = mark.firstElementChild as HTMLElement;

    expect(mark.style.width).toBe("8px");
    expect(Number.parseFloat(ring.style.width)).toBeGreaterThan(8);
  });
});
