import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { inject, injectable } from "inversify";
import type { FoldersService } from "../folders/folders";
import { FOLDERS_SERVICE } from "../folders/identifiers";
import {
  getMarketplaceInstallPaths,
  readSkillMetadataFromDir,
} from "../skills/skill-discovery";
import type { OnboardingImportService } from "./identifiers";
import type { OnboardingImportSummary } from "./schemas";

function toDisplayPath(absolutePath: string): string {
  const home = os.homedir();
  return absolutePath.startsWith(home)
    ? absolutePath.replace(home, "~")
    : absolutePath;
}

function readClaudeMcpServers(): { count: number; paths: string[] } {
  const file = path.join(os.homedir(), ".claude.json");
  try {
    const cfg = JSON.parse(fs.readFileSync(file, "utf-8")) as {
      mcpServers?: Record<string, unknown>;
    };
    const count =
      cfg.mcpServers && typeof cfg.mcpServers === "object"
        ? Object.keys(cfg.mcpServers).length
        : 0;
    return { count, paths: count > 0 ? [toDisplayPath(file)] : [] };
  } catch {
    return { count: 0, paths: [] };
  }
}

function readClaudePermissions(): { count: number; paths: string[] } {
  const file = path.join(os.homedir(), ".claude", "settings.json");
  try {
    const settings = JSON.parse(fs.readFileSync(file, "utf-8")) as {
      permissions?: { allow?: unknown; deny?: unknown };
    };
    const allow = Array.isArray(settings?.permissions?.allow)
      ? settings.permissions.allow.length
      : 0;
    const deny = Array.isArray(settings?.permissions?.deny)
      ? settings.permissions.deny.length
      : 0;
    const count = allow + deny;
    return { count, paths: count > 0 ? [toDisplayPath(file)] : [] };
  } catch {
    return { count: 0, paths: [] };
  }
}

@injectable()
export class OnboardingImportServiceImpl implements OnboardingImportService {
  constructor(
    @inject(FOLDERS_SERVICE)
    private readonly folders: FoldersService,
  ) {}

  async getSummary(): Promise<OnboardingImportSummary> {
    const folders = await this.folders.getFolders();
    const marketplacePaths = await getMarketplaceInstallPaths();

    const userSkillsDir = path.join(os.homedir(), ".claude", "skills");
    const repoSkillDirs = folders.map((f) => ({
      dir: path.join(f.path, ".claude", "skills"),
      name: f.name,
    }));
    const marketplaceSkillDirs = marketplacePaths.map((p) =>
      path.join(p, "skills"),
    );

    const [userSkills, repoResults, marketplaceResults] = await Promise.all([
      readSkillMetadataFromDir(userSkillsDir, "user"),
      Promise.all(
        repoSkillDirs.map(async (d) => ({
          dir: d.dir,
          skills: await readSkillMetadataFromDir(d.dir, "repo", d.name),
        })),
      ),
      Promise.all(
        marketplaceSkillDirs.map(async (dir) => ({
          dir,
          skills: await readSkillMetadataFromDir(dir, "marketplace"),
        })),
      ),
    ]);

    const skillsPaths = [
      ...(userSkills.length > 0 ? [userSkillsDir] : []),
      ...repoResults.filter((r) => r.skills.length > 0).map((r) => r.dir),
      ...marketplaceResults
        .filter((r) => r.skills.length > 0)
        .map((r) => r.dir),
    ].map(toDisplayPath);

    const skillsCount =
      userSkills.length +
      repoResults.reduce((sum, r) => sum + r.skills.length, 0) +
      marketplaceResults.reduce((sum, r) => sum + r.skills.length, 0);

    const plugins = {
      count: marketplacePaths.length,
      paths: marketplacePaths.map(toDisplayPath),
    };
    const mcpServers = readClaudeMcpServers();
    const permissions = readClaudePermissions();

    return {
      total: skillsCount + plugins.count + mcpServers.count + permissions.count,
      skills: { count: skillsCount, paths: skillsPaths },
      plugins,
      mcpServers,
      permissions,
    };
  }
}
