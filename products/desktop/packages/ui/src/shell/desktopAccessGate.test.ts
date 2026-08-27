import { describe, expect, it } from "vitest";
import { isBackgroundAccessRecheck } from "./desktopAccessGate";

describe("isBackgroundAccessRecheck", () => {
  it.each([
    {
      name: "recheck of the project the app already showed",
      lastAllowedProjectId: 42,
      currentProjectId: 42,
      accessStatus: "checking" as const,
      expected: true,
    },
    {
      name: "recheck after a project change",
      lastAllowedProjectId: 42,
      currentProjectId: 7,
      accessStatus: "checking" as const,
      expected: false,
    },
    {
      name: "first check with no previously allowed project",
      lastAllowedProjectId: null,
      currentProjectId: 42,
      accessStatus: "checking" as const,
      expected: false,
    },
    {
      name: "settled allowed result",
      lastAllowedProjectId: 42,
      currentProjectId: 42,
      accessStatus: "allowed" as const,
      expected: false,
    },
    {
      name: "settled blocked result",
      lastAllowedProjectId: 42,
      currentProjectId: 42,
      accessStatus: "blocked" as const,
      expected: false,
    },
    {
      name: "settled error result",
      lastAllowedProjectId: 42,
      currentProjectId: 42,
      accessStatus: "error" as const,
      expected: false,
    },
    {
      name: "unchecked state after a reset",
      lastAllowedProjectId: 42,
      currentProjectId: 42,
      accessStatus: "unchecked" as const,
      expected: false,
    },
  ])(
    "$name",
    ({ lastAllowedProjectId, currentProjectId, accessStatus, expected }) => {
      expect(
        isBackgroundAccessRecheck(
          lastAllowedProjectId,
          currentProjectId,
          accessStatus,
        ),
      ).toBe(expected);
    },
  );
});
