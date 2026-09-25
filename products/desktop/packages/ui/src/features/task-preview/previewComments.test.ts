import type { ResourceComment } from "@posthog/api-client/posthog-client";
import { describe, expect, it } from "vitest";
import { previewPins, previewThreads } from "./previewComments";

function comment(
  id: string,
  createdAt: string,
  context: unknown,
  sourceComment: string | null = null,
): ResourceComment {
  return {
    id,
    content: `Comment ${id}`,
    created_at: createdAt,
    created_by: null,
    item_id: "task-1:5173",
    item_context: context,
    scope: "task_preview",
    source_comment: sourceComment,
  } as ResourceComment;
}

function elementContext(path: string, selector: string) {
  return {
    anchor: {
      kind: "element",
      path,
      selector,
      tag: "button",
      text: "",
      html: "<button></button>",
      attributes: {},
    },
    taskId: "task-1",
  };
}

describe("preview comment pins", () => {
  it("numbers threads by age and pins only the open ones on their page", () => {
    const threads = previewThreads([
      comment("b", "2026-01-02T00:00:00Z", elementContext("/a?x=1", "#two")),
      comment("a", "2026-01-01T00:00:00Z", elementContext("/b#top", "#one")),
      comment("c", "2026-01-03T00:00:00Z", { anchor: { kind: "document" } }),
      comment("d", "2026-01-04T00:00:00Z", elementContext("/a", "#three")),
      comment(
        "d-resolve",
        "2026-01-05T00:00:00Z",
        { ...elementContext("/a", "#three"), threadState: "resolved" },
        "d",
      ),
    ]);

    expect(threads.map((thread) => [thread.id, thread.number])).toEqual([
      ["a", 1],
      ["b", 2],
      ["d", 3],
    ]);
    expect(previewPins(threads, "b")).toEqual([
      { id: "a", number: 1, path: "/b", selector: "#one", active: false },
      { id: "b", number: 2, path: "/a", selector: "#two", active: true },
    ]);
  });
});
