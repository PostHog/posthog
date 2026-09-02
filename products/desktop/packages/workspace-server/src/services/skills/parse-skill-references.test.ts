import { describe, expect, it } from "vitest";
import { parseSkillReferences } from "./parse-skill-references";

const KNOWN = new Set(["rs-review", "dep-skill", "usr", "foo", "My-Helper"]);

describe("parseSkillReferences", () => {
  it.each([
    ["a bare slash reference", "Run /rs-review on the diff.", ["rs-review"]],
    ["a reference at line start", "/rs-review\nthen stop", ["rs-review"]],
    [
      "backticked and quoted references",
      'Use `/rs-review` or "/dep-skill" here.',
      ["rs-review", "dep-skill"],
    ],
    ["a parenthesized reference", "(see /dep-skill)", ["dep-skill"]],
    ["a wiki-style link", "Details in [[dep-skill]].", ["dep-skill"]],
    [
      "mixed reference styles, deduplicated",
      "Run /rs-review, then [[rs-review]] again and /dep-skill.",
      ["rs-review", "dep-skill"],
    ],
    ["a sentence-final reference", "First run /dep-skill.", ["dep-skill"]],
    [
      "an uppercase frontmatter name",
      "Use /My-Helper then [[My-Helper]].",
      ["My-Helper"],
    ],
    ["an unknown skill name", "Run /not-a-skill now.", []],
    ["a URL path segment", "See https://example.com/foo for docs.", []],
    ["a file path segment", "Look in /usr/bin and /foo/bar.", []],
    ["a mid-word slash", "either/foo works", []],
    ["an empty body", "", []],
  ])("handles %s", (_label, content, expected) => {
    expect(parseSkillReferences(content, KNOWN)).toEqual(expected);
  });
});
