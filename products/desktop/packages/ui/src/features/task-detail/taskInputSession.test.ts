import { describe, expect, it } from "vitest";
import {
  getTaskInputSessionId,
  isTaskInputSessionId,
} from "./taskInputSession";

describe("task input sessions", () => {
  it("gives each browser tab an independent draft session", () => {
    const first = getTaskInputSessionId("tab-a");
    const second = getTaskInputSessionId("tab-b");

    expect(first).not.toBe(second);
    expect(isTaskInputSessionId(first)).toBe(true);
    expect(isTaskInputSessionId(second)).toBe(true);
    expect(getTaskInputSessionId(null)).toBe("task-input");
  });
});
