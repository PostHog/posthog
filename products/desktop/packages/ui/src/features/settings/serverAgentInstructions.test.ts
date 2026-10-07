import { describe, expect, it } from "vitest";
import {
  cloudTaskCarriesLocalInstructions,
  nextServerInstructions,
} from "./serverAgentInstructions";

describe("serverAgentInstructions", () => {
  it.each([
    ["nothing local to add", "Mine.", undefined, " ", { step: "done" }],
    [
      "the server already has the local text",
      "Mine.\n\nUse pnpm.",
      undefined,
      "Use pnpm.",
      { step: "done" },
    ],
    [
      "only the local copy has text",
      "",
      undefined,
      " Use pnpm. ",
      { step: "upload", instructions: "Use pnpm." },
    ],
    [
      "both have different text",
      "Mine.",
      undefined,
      "Use pnpm.",
      { step: "upload", instructions: "Mine.\n\nUse pnpm." },
    ],
    [
      "a Desktop edit replaces the uploaded part",
      "Mine.\n\nUse pnpm.",
      "Use pnpm.",
      "Use npm.",
      { step: "upload", instructions: "Mine.\n\nUse npm." },
    ],
    [
      "a cleared Desktop text removes the uploaded part",
      "Mine.\n\nUse pnpm.",
      "Use pnpm.",
      "",
      { step: "upload", instructions: "Mine." },
    ],
    [
      "the uploaded part was removed on web",
      "Mine.",
      "Use pnpm.",
      "Use npm.",
      { step: "upload", instructions: "Mine.\n\nUse npm." },
    ],
    [
      "the merged text is too long",
      "y".repeat(6_000),
      undefined,
      "x".repeat(15_000),
      { step: "keepLocal" },
    ],
  ] as const)("when %s", (_case, server, previous, local, expected) => {
    expect(nextServerInstructions({ server, previous, local })).toEqual(
      expected,
    );
  });

  it.each([
    ["the flag is off", false, 7, { "7": "Use pnpm." }, "Use pnpm.", true],
    ["nothing was uploaded", true, 7, {}, "Use pnpm.", true],
    [
      "the AGENTS.md snapshot is loading",
      true,
      7,
      { "7": "Use pnpm." },
      null,
      true,
    ],
    [
      "a Desktop edit is not uploaded yet",
      true,
      7,
      { "7": "Use pnpm." },
      "Use npm.",
      true,
    ],
    [
      "the server holds the current text",
      true,
      7,
      { "7": "Use pnpm." },
      "Use pnpm.",
      false,
    ],
  ] as const)(
    "carries the local copy when %s: %s",
    (_case, flagEnabled, projectId, onServer, local, expected) => {
      expect(
        cloudTaskCarriesLocalInstructions({
          flagEnabled,
          projectId,
          onServer,
          local,
        }),
      ).toBe(expected);
    },
  );
});
