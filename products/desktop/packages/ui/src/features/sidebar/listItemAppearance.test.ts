import type { TaskData } from "@posthog/core/sidebar/sidebarData.types";
import { describe, expect, it } from "vitest";
import {
  formatListItemMetadata,
  type ListItemMetadataField,
  moveListItemMetadataField,
  sanitizeListItemMetadataFields,
} from "./listItemAppearance";

const task: Pick<TaskData, "repository" | "branchName" | "linkedBranch"> = {
  repository: {
    fullPath: "posthog/code",
    name: "code",
    organization: "posthog",
  },
  branchName: "current-branch",
  linkedBranch: "linked-branch",
};

describe("list item appearance", () => {
  it.each<{
    label: string;
    taskValue: typeof task;
    creatorName: string | undefined;
    fields: ListItemMetadataField[];
    expected: string | undefined;
  }>([
    {
      label: "selected metadata in its configured order",
      taskValue: task,
      creatorName: "Ada Lovelace",
      fields: ["branch", "repository", "creator"],
      expected: "linked-branch · posthog/code · Ada Lovelace",
    },
    {
      label: "no second row when selected metadata is unavailable",
      taskValue: task,
      creatorName: undefined,
      fields: ["creator"],
      expected: undefined,
    },
    {
      label: "current branch when no linked branch exists",
      taskValue: { ...task, linkedBranch: null },
      creatorName: undefined,
      fields: ["branch"],
      expected: "current-branch",
    },
    {
      label: "local repository name without its absolute path",
      taskValue: {
        ...task,
        repository: { fullPath: "/Users/ada/code", name: "code" },
      },
      creatorName: undefined,
      fields: ["repository"],
      expected: "code",
    },
  ])("formats $label", ({ taskValue, creatorName, fields, expected }) => {
    expect(formatListItemMetadata(taskValue, creatorName, fields)).toBe(
      expected,
    );
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
