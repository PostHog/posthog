import { describe, expect, it } from "vitest";
import { quarantinedTaskId, takeQuarantinedRoute } from "./quarantinedRoute";

describe("quarantined route", () => {
  it.each([
    ["/spaces/s1/tasks/t1", "t1"],
    ["/tasks/t1?tab=diff", "t1"],
    ["/spaces/s1", null],
  ])("reads the task out of %s", (route, expected) => {
    expect(quarantinedTaskId(route)).toBe(expected);
  });

  it("reports the route once, then clears it", () => {
    window.history.replaceState(
      null,
      "",
      "/?quarantinedRoute=%2Fspaces%2Fs1%2Ftasks%2Ft1#/spaces/s1",
    );

    expect(takeQuarantinedRoute()).toBe("/spaces/s1/tasks/t1");
    expect(takeQuarantinedRoute()).toBeNull();
    expect(window.location.hash).toBe("#/spaces/s1");
  });
});
