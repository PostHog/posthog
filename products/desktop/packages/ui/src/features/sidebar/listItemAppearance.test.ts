import type { TaskData } from "@posthog/core/sidebar/sidebarData.types";
import { describe, expect, it } from "vitest";
import {
  type ListItemMetadataField,
  moveListItemMetadataField,
  sanitizeListItemMetadataFields,
  taskMetadataSegments,
} from "./listItemAppearance";

const task: Pick<
  TaskData,
  "repository" | "branchName" | "linkedBranch" | "lastActivityAt"
> = {
  repository: {
    fullPath: "posthog/code",
    name: "code",
    organization: "posthog",
  },
  branchName: "current-branch",
  linkedBranch: "linked-branch",
  lastActivityAt: 0,
};

describe("list item appearance", () => {
  it.each<{
    label: string;
    taskValue: typeof task;
    creatorName: string | undefined;
    fields: ListItemMetadataField[];
    expected: string[];
  }>([
    {
      label: "selected metadata in its configured order",
      taskValue: task,
      creatorName: "Ada Lovelace",
      fields: ["branch", "repository", "creator"],
      expected: ["linked-branch", "posthog/code", "Ada Lovelace"],
    },
    {
      label: "no second row when selected metadata is unavailable",
      taskValue: task,
      creatorName: undefined,
      fields: ["creator"],
      expected: [],
    },
    {
      label: "current branch when no linked branch exists",
      taskValue: { ...task, linkedBranch: null },
      creatorName: undefined,
      fields: ["branch"],
      expected: ["current-branch"],
    },
    {
      label: "local repository name without its absolute path",
      taskValue: {
        ...task,
        repository: { fullPath: "/Users/ada/code", name: "code" },
      },
      creatorName: undefined,
      fields: ["repository"],
      expected: ["code"],
    },
  ])("formats $label", ({ taskValue, creatorName, fields, expected }) => {
    expect(
      taskMetadataSegments(taskValue, creatorName, fields).map((s) => s.text),
    ).toEqual(expected);
  });

  // The short phrase is what a row has room for; the moment behind it is what
  // a reader needs when "3w ago" is not enough, and only the segment can carry
  // it to the tooltip.
  it("says how long ago the session moved, with the moment behind it", () => {
    const [segment] = taskMetadataSegments(
      { ...task, lastActivityAt: Date.now() - 2 * 3_600_000 },
      undefined,
      ["activity"],
    );

    expect(segment.text).toBe("2h ago");
    expect(segment.title).toBeTruthy();
  });

  it("drops the activity field for a session that never moved", () => {
    expect(
      taskMetadataSegments({ ...task, lastActivityAt: 0 }, undefined, [
        "activity",
      ]),
    ).toEqual([]);
  });

  // A row's height turns on whether it has a second row, so "nothing to show"
  // has to come back as nothing rather than as an empty row.
  it("returns no segments when nothing was chosen", () => {
    expect(taskMetadataSegments(task, "Ada Lovelace", [])).toEqual([]);
  });

  it("sanitizes persisted fields to known unique values", () => {
    expect(
      sanitizeListItemMetadataFields([
        "creator",
        "retired-field",
        7,
        "repository",
        "creator",
      ]),
    ).toEqual(["creator", "repository"]);
    expect(sanitizeListItemMetadataFields("branch")).toEqual([]);
  });

  it("moves a field to the target position", () => {
    expect(
      moveListItemMetadataField(
        ["repository", "branch", "creator"],
        "creator",
        "repository",
      ),
    ).toEqual(["creator", "repository", "branch"]);
  });
});
