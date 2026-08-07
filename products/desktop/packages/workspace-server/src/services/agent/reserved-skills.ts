import * as path from "node:path";
import type { Adapter } from "@posthog/shared";
import { getCodexSkillsDir } from "../posthog-plugin/codex-mirror";
import { getUserSkillsDir } from "../skills/skill-discovery";

export function getReservedSkillSourcePaths(args: {
  adapter: Adapter;
  bundledSkillsDir: string;
  externalPluginPaths: string[];
  userSkillsDir?: string;
  codexSkillsDir?: string;
}): string[] {
  if (args.adapter === "codex") {
    return [
      args.bundledSkillsDir,
      args.userSkillsDir ?? getUserSkillsDir(),
      args.codexSkillsDir ?? getCodexSkillsDir(),
    ];
  }
  return [
    args.bundledSkillsDir,
    ...args.externalPluginPaths.map((pluginPath) =>
      path.join(pluginPath, "skills"),
    ),
  ];
}
