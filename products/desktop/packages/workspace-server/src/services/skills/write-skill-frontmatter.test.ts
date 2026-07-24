import { describe, expect, it } from "vitest";
import { parseSkillFrontmatter } from "./parse-skill-frontmatter";
import { serializeSkillMarkdown } from "./write-skill-frontmatter";

describe("serializeSkillMarkdown", () => {
  it.each([
    ["plain values", "my-skill", "Does a thing"],
    ["empty description", "my-skill", ""],
    ["colon in description", "my-skill", "Use when: things break"],
    ["leading special char", "my-skill", "*very* important"],
    ["double quotes", "my-skill", 'Say "hello" politely'],
    ["backslashes", "my-skill", "Paths like C:\\Users\\foo"],
    [
      "multi-line description",
      "my-skill",
      "First line\nSecond line\nThird line",
    ],
    [
      "multi-paragraph description",
      "my-skill",
      "First paragraph\n\nSecond paragraph",
    ],
    ["hash that looks like a comment", "my-skill", "Use for #releases"],
  ])(
    "round-trips through parseSkillFrontmatter: %s",
    (_label, name, description) => {
      const content = serializeSkillMarkdown({ name, description }, "The body");

      const parsed = parseSkillFrontmatter(content);

      expect(parsed).toEqual({ name, description });
    },
  );

  it("appends the body after the frontmatter with a trailing newline", () => {
    const content = serializeSkillMarkdown(
      { name: "my-skill", description: "d" },
      "# Title\n\nSome body",
    );

    expect(content).toBe(
      "---\nname: my-skill\ndescription: d\n---\n\n# Title\n\nSome body\n",
    );
  });

  it("preserves the body verbatim including fake frontmatter fences", () => {
    const body = "intro\n---\nname: not-frontmatter\n---\n";
    const content = serializeSkillMarkdown(
      { name: "my-skill", description: "d" },
      body,
    );

    const parsed = parseSkillFrontmatter(content);
    expect(parsed?.name).toBe("my-skill");
    expect(content).toContain("intro\n---\nname: not-frontmatter");
  });
});
