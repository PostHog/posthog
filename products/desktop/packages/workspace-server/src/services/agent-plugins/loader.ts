import * as fs from "node:fs";
import * as path from "node:path";
import { parseDocument } from "yaml";
import {
  AGENT_PLUGINS_MANIFEST_SCHEMA,
  type AgentPluginDiagnostic,
  type AgentPluginManifest,
  type AgentPluginPreview,
  type AgentPluginSkill,
} from "./schemas";

const PLUGIN_NAME_PATTERN =
  /^(?!.*(?:--|\.\.))[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?$/;
const SKILL_NAME_PATTERN = /^(?!.*--)[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$/;
const MANIFEST_FIELDS = new Set([
  "$schema",
  "name",
  "version",
  "description",
  "author",
  "homepage",
  "repository",
  "license",
  "keywords",
  "extensions",
]);
const AUTHOR_FIELDS = new Set(["name", "email", "url"]);

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function isPathContained(root: string, candidate: string): boolean {
  const relativePath = path.relative(root, candidate);
  return (
    relativePath === "" ||
    (!relativePath.startsWith(`..${path.sep}`) &&
      relativePath !== ".." &&
      !path.isAbsolute(relativePath))
  );
}

function diagnostic(
  severity: AgentPluginDiagnostic["severity"],
  code: string,
  message: string,
  diagnosticPath?: string,
): AgentPluginDiagnostic {
  return {
    severity,
    code,
    message,
    ...(diagnosticPath ? { path: diagnosticPath } : {}),
  };
}

function validateOptionalString(
  raw: Record<string, unknown>,
  field: string,
  diagnostics: AgentPluginDiagnostic[],
): string | undefined {
  const value = raw[field];
  if (value === undefined) return undefined;
  if (typeof value !== "string") {
    diagnostics.push(
      diagnostic("error", "invalid_manifest", `${field} must be a string.`),
    );
    return undefined;
  }
  return value;
}

function parseManifest(
  value: unknown,
  diagnostics: AgentPluginDiagnostic[],
): AgentPluginManifest | null {
  if (!isObject(value)) {
    diagnostics.push(
      diagnostic(
        "error",
        "invalid_manifest",
        "plugin.json must contain an object.",
      ),
    );
    return null;
  }

  for (const field of Object.keys(value)) {
    if (!MANIFEST_FIELDS.has(field)) {
      diagnostics.push(
        diagnostic(
          "warning",
          "unknown_manifest_field",
          `Ignored unknown plugin.json field: ${field}.`,
        ),
      );
    }
  }

  if (value.extensions !== undefined && !isObject(value.extensions)) {
    diagnostics.push(
      diagnostic(
        "warning",
        "invalid_extensions",
        "Ignored extensions because it is not an object.",
      ),
    );
  }

  if (value.$schema !== AGENT_PLUGINS_MANIFEST_SCHEMA) {
    diagnostics.push(
      diagnostic(
        "error",
        "unsupported_schema",
        `plugin.json must target ${AGENT_PLUGINS_MANIFEST_SCHEMA}.`,
      ),
    );
  }

  const name = value.name;
  if (
    typeof name !== "string" ||
    name.length < 1 ||
    name.length > 64 ||
    !PLUGIN_NAME_PATTERN.test(name)
  ) {
    diagnostics.push(
      diagnostic(
        "error",
        "invalid_manifest_name",
        "Plugin name must use 1-64 lowercase letters, numbers, hyphens, or periods without repeated separators.",
      ),
    );
  }

  const version = validateOptionalString(value, "version", diagnostics);
  const description = validateOptionalString(value, "description", diagnostics);
  const homepage = validateOptionalString(value, "homepage", diagnostics);
  const repository = validateOptionalString(value, "repository", diagnostics);
  const license = validateOptionalString(value, "license", diagnostics);

  let author: AgentPluginManifest["author"];
  if (value.author !== undefined) {
    if (!isObject(value.author)) {
      diagnostics.push(
        diagnostic("error", "invalid_manifest", "author must be an object."),
      );
    } else {
      for (const field of Object.keys(value.author)) {
        if (!AUTHOR_FIELDS.has(field)) {
          diagnostics.push(
            diagnostic(
              "error",
              "invalid_manifest",
              `author contains unknown field: ${field}.`,
            ),
          );
        }
      }
      const nameValue = validateOptionalString(
        value.author,
        "name",
        diagnostics,
      );
      const email = validateOptionalString(value.author, "email", diagnostics);
      const url = validateOptionalString(value.author, "url", diagnostics);
      author = {
        ...(nameValue !== undefined ? { name: nameValue } : {}),
        ...(email !== undefined ? { email } : {}),
        ...(url !== undefined ? { url } : {}),
      };
    }
  }

  let keywords: string[] | undefined;
  if (value.keywords !== undefined) {
    if (
      !Array.isArray(value.keywords) ||
      !value.keywords.every((keyword) => typeof keyword === "string")
    ) {
      diagnostics.push(
        diagnostic(
          "error",
          "invalid_manifest",
          "keywords must be an array of strings.",
        ),
      );
    } else {
      keywords = value.keywords;
    }
  }

  if (diagnostics.some((item) => item.severity === "error")) return null;

  return {
    $schema: AGENT_PLUGINS_MANIFEST_SCHEMA,
    name: name as string,
    ...(version !== undefined ? { version } : {}),
    ...(description !== undefined ? { description } : {}),
    ...(author !== undefined ? { author } : {}),
    ...(homepage !== undefined ? { homepage } : {}),
    ...(repository !== undefined ? { repository } : {}),
    ...(license !== undefined ? { license } : {}),
    ...(keywords !== undefined ? { keywords } : {}),
  };
}

async function validateSkillTree(
  pluginRoot: string,
  skillRoot: string,
): Promise<string | null> {
  const visited = new Set<string>();

  const walk = async (directory: string): Promise<string | null> => {
    const resolvedDirectory = await fs.promises.realpath(directory);
    if (!isPathContained(pluginRoot, resolvedDirectory)) {
      return "Skill files must remain inside the plugin directory.";
    }
    if (visited.has(resolvedDirectory)) return null;
    visited.add(resolvedDirectory);

    const entries = await fs.promises.readdir(resolvedDirectory, {
      withFileTypes: true,
    });
    for (const entry of entries) {
      const entryPath = path.join(resolvedDirectory, entry.name);
      const lstat = await fs.promises.lstat(entryPath);
      if (lstat.isSymbolicLink()) {
        return "Skill directories cannot contain symbolic links.";
      }
      const resolvedEntry = await fs.promises.realpath(entryPath);
      if (!isPathContained(pluginRoot, resolvedEntry)) {
        return "Skill files must remain inside the plugin directory.";
      }
      if (lstat.isDirectory()) {
        const error = await walk(resolvedEntry);
        if (error) return error;
      } else if (!lstat.isFile()) {
        return "Skill directories can contain only regular files and directories.";
      }
    }
    return null;
  };

  return walk(skillRoot);
}

function parseSkillFrontmatter(
  content: string,
  directoryName: string,
): { name: string; description: string } | string {
  const match = content.match(/^---\r?\n([\s\S]*?)\r?\n---(?:\r?\n|$)/);
  if (!match) return "SKILL.md must start with YAML frontmatter.";

  const document = parseDocument(match[1], { prettyErrors: false });
  if (document.errors.length > 0)
    return "SKILL.md frontmatter is not valid YAML.";
  const value: unknown = document.toJS();
  if (!isObject(value)) return "SKILL.md frontmatter must be an object.";

  const name = value.name;
  if (
    typeof name !== "string" ||
    name.length < 1 ||
    name.length > 64 ||
    !SKILL_NAME_PATTERN.test(name)
  ) {
    return "Skill name must use 1-64 lowercase letters, numbers, or hyphens without repeated hyphens.";
  }
  if (name !== directoryName) {
    return "Skill name must match its parent directory name.";
  }

  const description = value.description;
  if (
    typeof description !== "string" ||
    description.length < 1 ||
    description.length > 1024
  ) {
    return "Skill description must contain 1-1024 characters.";
  }

  if (value.license !== undefined && typeof value.license !== "string") {
    return "Skill license must be a string.";
  }
  if (
    value.compatibility !== undefined &&
    (typeof value.compatibility !== "string" ||
      value.compatibility.length < 1 ||
      value.compatibility.length > 500)
  ) {
    return "Skill compatibility must contain 1-500 characters.";
  }
  if (value.metadata !== undefined) {
    if (
      !isObject(value.metadata) ||
      !Object.values(value.metadata).every((entry) => typeof entry === "string")
    ) {
      return "Skill metadata must map strings to strings.";
    }
  }
  if (
    value["allowed-tools"] !== undefined &&
    typeof value["allowed-tools"] !== "string"
  ) {
    return "Skill allowed-tools must be a string.";
  }

  return { name, description };
}

export async function validateAgentPluginSkillSnapshot(
  pluginRoot: string,
  skillRoot: string,
  skillName: string,
): Promise<string | null> {
  const resolvedPluginRoot = await fs.promises.realpath(pluginRoot);
  const resolvedSkillRoot = await fs.promises.realpath(skillRoot);
  const treeError = await validateSkillTree(
    resolvedPluginRoot,
    resolvedSkillRoot,
  );
  if (treeError) return treeError;

  const content = await fs.promises.readFile(
    path.join(resolvedSkillRoot, "SKILL.md"),
    "utf8",
  );
  const frontmatter = parseSkillFrontmatter(content, skillName);
  return typeof frontmatter === "string" ? frontmatter : null;
}

async function loadSkills(
  pluginRoot: string,
  diagnostics: AgentPluginDiagnostic[],
): Promise<AgentPluginSkill[]> {
  const skillsPath = path.join(pluginRoot, "skills");
  let resolvedSkillsPath: string;
  try {
    resolvedSkillsPath = await fs.promises.realpath(skillsPath);
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") return [];
    diagnostics.push(
      diagnostic(
        "error",
        "invalid_skills",
        "Could not read the skills directory.",
        "skills",
      ),
    );
    return [];
  }

  if (!isPathContained(pluginRoot, resolvedSkillsPath)) {
    diagnostics.push(
      diagnostic(
        "error",
        "skills_escape",
        "The skills directory resolves outside the plugin directory.",
        "skills",
      ),
    );
    return [];
  }

  let entries: fs.Dirent[];
  try {
    const skillsStat = await fs.promises.stat(resolvedSkillsPath);
    if (!skillsStat.isDirectory()) {
      diagnostics.push(
        diagnostic(
          "error",
          "invalid_skills",
          "skills must be a directory.",
          "skills",
        ),
      );
      return [];
    }
    entries = await fs.promises.readdir(resolvedSkillsPath, {
      withFileTypes: true,
    });
  } catch {
    diagnostics.push(
      diagnostic(
        "error",
        "invalid_skills",
        "Could not read the skills directory.",
        "skills",
      ),
    );
    return [];
  }
  const skills: AgentPluginSkill[] = [];
  for (const entry of entries.sort((a, b) => a.name.localeCompare(b.name))) {
    if (entry.isSymbolicLink()) {
      diagnostics.push(
        diagnostic(
          "error",
          "invalid_skill",
          `Skipped ${entry.name}: skill directories cannot be symbolic links.`,
          `skills/${entry.name}`,
        ),
      );
      continue;
    }
    if (!entry.isDirectory()) continue;
    const skillDirectory = path.join(resolvedSkillsPath, entry.name);
    const skillMdPath = path.join(skillDirectory, "SKILL.md");

    let resolvedSkillMd: string;
    try {
      resolvedSkillMd = await fs.promises.realpath(skillMdPath);
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code === "ENOENT") continue;
      diagnostics.push(
        diagnostic(
          "error",
          "invalid_skill",
          `Skipped ${entry.name}: SKILL.md could not be read.`,
          `skills/${entry.name}/SKILL.md`,
        ),
      );
      continue;
    }

    try {
      const resolvedSkillDirectory = await fs.promises.realpath(skillDirectory);
      if (
        !isPathContained(pluginRoot, resolvedSkillDirectory) ||
        !isPathContained(pluginRoot, resolvedSkillMd)
      ) {
        diagnostics.push(
          diagnostic(
            "error",
            "skill_escape",
            "Skipped skill because it resolves outside the plugin directory.",
            `skills/${entry.name}`,
          ),
        );
        continue;
      }
      const skillDirectoryStat = await fs.promises.lstat(skillDirectory);
      const skillMdStat = await fs.promises.lstat(skillMdPath);
      if (
        skillDirectoryStat.isSymbolicLink() ||
        skillMdStat.isSymbolicLink() ||
        !skillMdStat.isFile()
      ) {
        diagnostics.push(
          diagnostic(
            "error",
            "invalid_skill",
            `Skipped ${entry.name}: SKILL.md must be a regular file.`,
            `skills/${entry.name}/SKILL.md`,
          ),
        );
        continue;
      }

      const treeError = await validateSkillTree(
        pluginRoot,
        resolvedSkillDirectory,
      );
      if (treeError) {
        diagnostics.push(
          diagnostic(
            "error",
            "skill_escape",
            `Skipped ${entry.name}: ${treeError}`,
            `skills/${entry.name}`,
          ),
        );
        continue;
      }

      const content = await fs.promises.readFile(resolvedSkillMd, "utf8");
      const frontmatter = parseSkillFrontmatter(content, entry.name);
      if (typeof frontmatter === "string") {
        diagnostics.push(
          diagnostic(
            "error",
            "invalid_skill",
            `Skipped ${entry.name}: ${frontmatter}`,
            `skills/${entry.name}/SKILL.md`,
          ),
        );
        continue;
      }
      skills.push({
        name: frontmatter.name,
        description: frontmatter.description,
        path: resolvedSkillDirectory,
      });
    } catch {
      diagnostics.push(
        diagnostic(
          "error",
          "invalid_skill",
          `Skipped ${entry.name}: the skill could not be read.`,
          `skills/${entry.name}`,
        ),
      );
    }
  }
  return skills;
}

export async function loadAgentPlugin(
  sourcePath: string,
): Promise<AgentPluginPreview> {
  const diagnostics: AgentPluginDiagnostic[] = [];
  let pluginRoot: string;
  try {
    pluginRoot = await fs.promises.realpath(path.resolve(sourcePath));
    const rootStat = await fs.promises.stat(pluginRoot);
    if (!rootStat.isDirectory()) {
      diagnostics.push(
        diagnostic(
          "error",
          "invalid_root",
          "The selected path is not a directory.",
        ),
      );
      return {
        valid: false,
        sourcePath: path.resolve(sourcePath),
        manifest: null,
        skills: [],
        diagnostics,
      };
    }
  } catch {
    diagnostics.push(
      diagnostic(
        "error",
        "invalid_root",
        "The selected directory could not be read.",
      ),
    );
    return {
      valid: false,
      sourcePath: path.resolve(sourcePath),
      manifest: null,
      skills: [],
      diagnostics,
    };
  }

  const manifestPath = path.join(pluginRoot, "plugin.json");
  let rawManifest: unknown;
  try {
    const resolvedManifestPath = await fs.promises.realpath(manifestPath);
    if (!isPathContained(pluginRoot, resolvedManifestPath)) {
      diagnostics.push(
        diagnostic(
          "error",
          "manifest_escape",
          "plugin.json resolves outside the plugin directory.",
          "plugin.json",
        ),
      );
      return {
        valid: false,
        sourcePath: pluginRoot,
        manifest: null,
        skills: [],
        diagnostics,
      };
    }
    const stat = await fs.promises.stat(resolvedManifestPath);
    if (!stat.isFile()) throw new Error("not a file");
    rawManifest = JSON.parse(
      await fs.promises.readFile(resolvedManifestPath, "utf8"),
    );
  } catch (error) {
    diagnostics.push(
      diagnostic(
        "error",
        "invalid_manifest",
        error instanceof SyntaxError
          ? "plugin.json is not valid JSON."
          : "plugin.json is missing or is not a regular file.",
        "plugin.json",
      ),
    );
    return {
      valid: false,
      sourcePath: pluginRoot,
      manifest: null,
      skills: [],
      diagnostics,
    };
  }

  const manifest = parseManifest(rawManifest, diagnostics);
  if (!manifest) {
    return {
      valid: false,
      sourcePath: pluginRoot,
      manifest: null,
      skills: [],
      diagnostics,
    };
  }

  const skills = await loadSkills(pluginRoot, diagnostics);
  return {
    valid: true,
    sourcePath: pluginRoot,
    manifest,
    skills,
    diagnostics,
  };
}
