import type { TaskData } from "@posthog/core/sidebar/sidebarData.types";
import { describe, expect, it } from "vitest";
import {
  getPinDropAction,
  getPinnedInsertionIndex,
  isPointInsideRect,
} from "./taskListDragAndDrop";

const task = (
  id: string,
  createdAt: number,
  lastActivityAt = createdAt,
): TaskData => ({
  id,
  title: id,
  createdAt,
  lastActivityAt,
  isGenerating: false,
  isUnread: false,
  isPinned: true,
  needsPermission: false,
  repository: null,
  isSuspended: false,
  folderPath: null,
  cloudPrUrl: null,
  branchName: null,
  linkedBranch: null,
});

describe("task list drag and drop", () => {
  it.each([
    {
      name: "pins an unpinned session dropped over pinned",
      sourcePinned: false,
      overPinned: true,
      expected: true,
    },
    {
      name: "unpins a pinned session dropped outside pinned",
      sourcePinned: true,
      overPinned: false,
      expected: false,
    },
    {
      name: "keeps an unpinned session outside pinned",
      sourcePinned: false,
      overPinned: false,
      expected: null,
    },
    {
      name: "keeps a pinned session inside pinned",
      sourcePinned: true,
      overPinned: true,
      expected: null,
    },
  ])("$name", ({ sourcePinned, overPinned, expected }) => {
    expect(getPinDropAction(sourcePinned, overPinned)).toBe(expected);
  });

  it("opens the pinned gap at the session's final sorted position", () => {
    const dragged = task("dragged", 30, 15);
    const pinned = [task("newest", 50, 50), dragged, task("oldest", 10, 10)];

    expect(getPinnedInsertionIndex(pinned, dragged, "createdAt")).toBe(1);
    expect(getPinnedInsertionIndex(pinned, dragged, "lastActivityAt")).toBe(1);
  });

  it.each([
    { point: { x: 10, y: 10 }, expected: true },
    { point: { x: 20, y: 20 }, expected: true },
    { point: { x: 21, y: 10 }, expected: false },
    { point: { x: 10, y: 4 }, expected: false },
  ])("detects pinned bounds for $point", ({ point, expected }) => {
    expect(
      isPointInsideRect(point, {
        top: 5,
        right: 20,
        bottom: 20,
        left: 5,
      }),
    ).toBe(expected);
  });
});
