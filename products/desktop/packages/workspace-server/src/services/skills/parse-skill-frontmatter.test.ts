import { describe, expect, it } from "vitest";
import {
  parseSkillDependencies,
  parseSkillFrontmatter,
} from "./parse-skill-frontmatter";

describe("parseSkillFrontmatter disable-model-invocation", () => {
  it.each([
    ["absent", `---\nname: a\ndescription: d\n---\nbody`, false],
    [
      "true",
      `---\nname: a\ndescription: d\ndisable-model-invocation: true\n---\nbody`,
      true,
    ],
    [
      "capitalized True",
      `---\nname: a\ndescription: d\ndisable-model-invocation: True\n---\nbody`,
      true,
    ],
    [
      "quoted true",
      `---\nname: a\ndescription: d\ndisable-model-invocation: "true"\n---\nbody`,
      true,
    ],
    [
      "false",
      `---\nname: a\ndescription: d\ndisable-model-invocation: false\n---\nbody`,
      false,
    ],
    [
      "non-boolean value",
      `---\nname: a\ndescription: d\ndisable-model-invocation: maybe\n---\nbody`,
      false,
    ],
    [
      "true with trailing comment",
      `---\nname: a\ndescription: d\ndisable-model-invocation: true  # manual only\n---\nbody`,
      true,
    ],
    [
      "quoted true with trailing comment",
      `---\nname: a\ndescription: d\ndisable-model-invocation: "true" # manual only\n---\nbody`,
      true,
    ],
    [
      "false with trailing comment",
      `---\nname: a\ndescription: d\ndisable-model-invocation: false # keep automatic\n---\nbody`,
      false,
    ],
    [
      "quoted string that only starts with true",
      `---\nname: a\ndescription: d\ndisable-model-invocation: "true # manual only"\n---\nbody`,
      false,
    ],
  ])("parses %s", (_label, content, expected) => {
    expect(parseSkillFrontmatter(content)?.disableModelInvocation).toBe(
      expected,
    );
  });
});

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
