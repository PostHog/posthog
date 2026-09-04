import { describe, expect, it } from "vitest";
import {
  isBackgroundAccessRecheck,
  nextLastAllowedProjectId,
} from "./desktopAccessGate";

describe("desktopAccessGate", () => {
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

  describe("nextLastAllowedProjectId", () => {
    it.each([
      {
        name: "records the project on an allowed result",
        previous: null,
        state: {
          isAuthenticated: true,
          currentProjectId: 42,
          accessIsCurrent: true,
          accessStatus: "allowed" as const,
        },
        expected: 42,
      },
      {
        name: "clears on a settled blocked result",
        previous: 42,
        state: {
          isAuthenticated: true,
          currentProjectId: 42,
          accessIsCurrent: true,
          accessStatus: "blocked" as const,
        },
        expected: null,
      },
      {
        name: "clears on a settled error result",
        previous: 42,
        state: {
          isAuthenticated: true,
          currentProjectId: 42,
          accessIsCurrent: true,
          accessStatus: "error" as const,
        },
        expected: null,
      },
      {
        name: "clears on sign-out",
        previous: 42,
        state: {
          isAuthenticated: false,
          currentProjectId: 42,
          accessIsCurrent: true,
          accessStatus: "allowed" as const,
        },
        expected: null,
      },
      {
        name: "keeps the marker through a recheck",
        previous: 42,
        state: {
          isAuthenticated: true,
          currentProjectId: 42,
          accessIsCurrent: true,
          accessStatus: "checking" as const,
        },
        expected: 42,
      },
      {
        name: "keeps the marker while the access record lags a project switch",
        previous: 42,
        state: {
          isAuthenticated: true,
          currentProjectId: 7,
          accessIsCurrent: false,
          accessStatus: "blocked" as const,
        },
        expected: 42,
      },
    ])("$name", ({ previous, state, expected }) => {
      expect(nextLastAllowedProjectId(previous, state)).toBe(expected);
    });

    it("gates a retry from the denial screen instead of mounting the app", () => {
      // allowed -> blocked -> retry publishes "checking" for the same
      // project. Without the clear on "blocked", the retry counts as a
      // background recheck and the whole app mounts before the check answers.
      const afterAllowed = nextLastAllowedProjectId(null, {
        isAuthenticated: true,
        currentProjectId: 42,
        accessIsCurrent: true,
        accessStatus: "allowed",
      });
      const afterBlocked = nextLastAllowedProjectId(afterAllowed, {
        isAuthenticated: true,
        currentProjectId: 42,
        accessIsCurrent: true,
        accessStatus: "blocked",
      });
      expect(isBackgroundAccessRecheck(afterBlocked, 42, "checking")).toBe(
        false,
      );
    });
  });
});
