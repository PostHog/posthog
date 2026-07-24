import { describe, expect, it } from "vitest";
import { parseSkillDependencies } from "./parse-skill-frontmatter";

describe("parseSkillDependencies", () => {
  it.each([
    ["absent", `---\nname: a\ndescription: d\n---\nbody`, []],
    [
      "block sequence",
      `---\nname: a\ndependencies:\n  - one\n  - two\n---\nbody`,
      ["one", "two"],
    ],
    [
      "flow sequence",
      `---\nname: a\ndependencies: [one, two]\n---\nbody`,
      ["one", "two"],
    ],
    [
      "quoted entries",
      `---\nname: a\ndependencies:\n  - "one"\n  - 'two'\n---\nbody`,
      ["one", "two"],
    ],
    ["no frontmatter", `just a body`, []],
  ])("parses %s", (_label, content, expected) => {
    expect(parseSkillDependencies(content)).toEqual(expected);
  });
});
