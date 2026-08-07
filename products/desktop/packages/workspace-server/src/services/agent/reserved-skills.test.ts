import { describe, expect, it } from "vitest";
import { getReservedSkillSourcePaths } from "./reserved-skills";

describe("Agent Plugin reserved skill sources", () => {
  it("does not reserve Claude-only plugin skills for Codex", () => {
    expect(
      getReservedSkillSourcePaths({
        adapter: "codex",
        bundledSkillsDir: "/bundled/skills",
        externalPluginPaths: ["/claude-marketplace/plugin"],
        userSkillsDir: "/user/claude/skills",
        codexSkillsDir: "/user/codex/skills",
      }),
    ).toEqual(["/bundled/skills", "/user/claude/skills", "/user/codex/skills"]);
  });

  it("reserves every Claude plugin skill source for Claude", () => {
    expect(
      getReservedSkillSourcePaths({
        adapter: "claude",
        bundledSkillsDir: "/bundled/skills",
        externalPluginPaths: ["/repo/plugin", "/marketplace/plugin"],
      }),
    ).toEqual([
      "/bundled/skills",
      "/repo/plugin/skills",
      "/marketplace/plugin/skills",
    ]);
  });
});
