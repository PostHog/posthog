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

const idle: TaskDot = {
  tone: "gray",
  style: "hollow",
  pulse: false,
  label: "All caught up",
};

describe("TaskStatusDot", () => {
  // The two halves of the same constraint, and the pair is the point: the ring
  // has to outgrow the column to read as a ring at all, and the column has to
  // stay the plain dot's or every working row's label steps right of its
  // neighbours'. Measured against a rendered plain dot rather than a hardcoded
  // 8px, so retuning the vocabulary's sizes moves both marks together.
  //
  // jsdom lays nothing out, so this reaches the sizes the component sets and
  // stops there. Whether the ring is legible at that size, and whether it is
  // clipped by anything upstream, is not a claim this test makes.
  it("draws the working ring larger than the column it sits in", () => {
    render(
      <>
        <TaskStatusDot dot={working} />
        <TaskStatusDot dot={idle} />
      </>,
    );

    const column = screen.getByRole("img", { name: "All caught up" }).style
      .width;
    const mark = screen.getByRole("img", { name: "Working" });
    const ring = mark.firstElementChild as HTMLElement;

    expect(mark.style.width).toBe(column);
    expect(Number.parseFloat(ring.style.width)).toBeGreaterThan(
      Number.parseFloat(column),
    );
  });
});
