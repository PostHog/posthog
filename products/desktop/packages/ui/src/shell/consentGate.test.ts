import { describe, expect, it } from "vitest";
import {
  isBackgroundConsentRecheck,
  nextLastSatisfiedOrgId,
} from "./consentGate";

describe("consentGate", () => {
  describe("isBackgroundConsentRecheck", () => {
    it.each([
      {
        name: "recheck for the organization the app already showed",
        lastSatisfiedOrgId: "org-1",
        currentOrgId: "org-1",
        consentStatus: "loading" as const,
        expected: true,
      },
      {
        name: "recheck after an organization change",
        lastSatisfiedOrgId: "org-1",
        currentOrgId: "org-2",
        consentStatus: "loading" as const,
        expected: false,
      },
      {
        name: "first check with no previously satisfied organization",
        lastSatisfiedOrgId: null,
        currentOrgId: "org-1",
        consentStatus: "loading" as const,
        expected: false,
      },
      {
        name: "settled resolved result",
        lastSatisfiedOrgId: "org-1",
        currentOrgId: "org-1",
        consentStatus: "resolved" as const,
        expected: false,
      },
      {
        name: "settled error result",
        lastSatisfiedOrgId: "org-1",
        currentOrgId: "org-1",
        consentStatus: "error" as const,
        expected: false,
      },
    ])(
      "$name",
      ({ lastSatisfiedOrgId, currentOrgId, consentStatus, expected }) => {
        expect(
          isBackgroundConsentRecheck(
            lastSatisfiedOrgId,
            currentOrgId,
            consentStatus,
          ),
        ).toBe(expected);
      },
    );
  });

  describe("nextLastSatisfiedOrgId", () => {
    it.each([
      {
        name: "records the organization on a satisfied result",
        previous: null,
        state: {
          isAuthenticated: true,
          currentOrgId: "org-1",
          consentStatus: "resolved" as const,
          consentSatisfied: true,
        },
        expected: "org-1",
      },
      {
        name: "clears on a settled unsatisfied result",
        previous: "org-1",
        state: {
          isAuthenticated: true,
          currentOrgId: "org-1",
          consentStatus: "resolved" as const,
          consentSatisfied: false,
        },
        expected: null,
      },
      {
        name: "clears on a settled error result",
        previous: "org-1",
        state: {
          isAuthenticated: true,
          currentOrgId: "org-1",
          consentStatus: "error" as const,
          consentSatisfied: false,
        },
        expected: null,
      },
      {
        name: "clears on sign-out",
        previous: "org-1",
        state: {
          isAuthenticated: false,
          currentOrgId: "org-1",
          consentStatus: "resolved" as const,
          consentSatisfied: true,
        },
        expected: null,
      },
      {
        name: "keeps the marker through a recheck",
        previous: "org-1",
        state: {
          isAuthenticated: true,
          currentOrgId: "org-1",
          consentStatus: "loading" as const,
          consentSatisfied: false,
        },
        expected: "org-1",
      },
    ])("$name", ({ previous, state, expected }) => {
      expect(nextLastSatisfiedOrgId(previous, state)).toBe(expected);
    });

    it("gates a retry from the consent screen instead of mounting the app", () => {
      // satisfied -> unsatisfied -> retry publishes "loading" for the same
      // organization. Without the clear on the unsatisfied result, the retry
      // counts as a background recheck and the whole app mounts before the
      // check answers.
      const afterSatisfied = nextLastSatisfiedOrgId(null, {
        isAuthenticated: true,
        currentOrgId: "org-1",
        consentStatus: "resolved",
        consentSatisfied: true,
      });
      const afterRevoked = nextLastSatisfiedOrgId(afterSatisfied, {
        isAuthenticated: true,
        currentOrgId: "org-1",
        consentStatus: "resolved",
        consentSatisfied: false,
      });
      expect(isBackgroundConsentRecheck(afterRevoked, "org-1", "loading")).toBe(
        false,
      );
    });
  });
});
