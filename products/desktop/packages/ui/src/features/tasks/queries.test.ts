import { ApiRequestError } from "@posthog/api-client/fetcher";
import { describe, expect, it } from "vitest";
import { isTaskDetailNotFoundError } from "./queries";

describe("task queries", () => {
  it("detects task detail 404 errors from the shared API fetcher", () => {
    expect(
      isTaskDetailNotFoundError(
        new ApiRequestError(404, '{"detail":"Not found."}'),
      ),
    ).toBe(true);
    expect(
      isTaskDetailNotFoundError(
        new ApiRequestError(500, '{"detail":"Server error."}'),
      ),
    ).toBe(false);
    // A plain error merely mentioning a 404 (e.g. quoting an upstream body)
    // must not read as one.
    expect(isTaskDetailNotFoundError(new Error("Failed request: [404]"))).toBe(
      false,
    );
  });
});
