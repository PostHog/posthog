import { describe, expect, it } from "vitest";
import {
  cloudTaskCarriesLocalInstructions,
  nextInstructionsMove,
} from "./serverAgentInstructions";

describe("serverAgentInstructions", () => {
  it.each([
    [
      "the file snapshot is not loaded yet",
      false,
      "Use pnpm.",
      "",
      { step: "wait" },
    ],
    ["there is nothing local to move", true, "  ", "Mine.", { step: "done" }],
    [
      "the server already has the local text",
      true,
      "Use pnpm.",
      "Mine.\n\nUse pnpm.",
      { step: "done" },
    ],
    [
      "only the local copy has instructions",
      true,
      " Use pnpm. ",
      "",
      { step: "upload", instructions: "Use pnpm." },
    ],
    [
      "both have different text",
      true,
      "Use pnpm.",
      "Mine.",
      { step: "upload", instructions: "Mine.\n\nUse pnpm." },
    ],
    [
      "the merged text is too long",
      true,
      "x".repeat(15_000),
      "y".repeat(6_000),
      { step: "keepLocal" },
    ],
  ] as const)("when %s", (_case, localReady, local, server, expected) => {
    expect(nextInstructionsMove({ localReady, local, server })).toEqual(
      expected,
    );
  });

  it.each([
    [false, 7, [7], true],
    [true, 7, [], true],
    [true, null, [7], true],
    [true, 7, [7], false],
  ] as const)(
    "flag %s, project %s, moved %j: carries local copy %s",
    (flagEnabled, projectId, onServerProjectIds, expected) => {
      expect(
        cloudTaskCarriesLocalInstructions({
          flagEnabled,
          projectId,
          onServerProjectIds,
        }),
      ).toBe(expected);
    },
  );
});
