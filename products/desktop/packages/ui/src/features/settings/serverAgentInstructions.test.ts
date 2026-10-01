import { describe, expect, it } from "vitest";
import {
  cloudTaskCarriesLocalInstructions,
  nextInstructionsMoveStep,
} from "./serverAgentInstructions";

describe("serverAgentInstructions", () => {
  it.each([
    ["the file snapshot is not loaded yet", false, "Use pnpm.", "", "wait"],
    ["the server already has instructions", true, "Use pnpm.", "Mine.", "done"],
    ["there is nothing local to move", true, "  ", "", "done"],
    ["only the local copy has instructions", true, "Use pnpm.", "", "upload"],
  ] as const)("returns %s → %s", (_case, localReady, local, server, step) => {
    expect(nextInstructionsMoveStep({ localReady, local, server })).toBe(step);
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
