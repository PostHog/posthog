import * as fs from "node:fs";
import * as net from "node:net";
import * as path from "node:path";
import { parseDocument } from "yaml";
import {
  AGENT_PLUGINS_MANIFEST_SCHEMA,
  AGENT_PLUGINS_MCP_SCHEMA,
  type AgentPluginDiagnostic,
  type AgentPluginHttpMcpServer,
  type AgentPluginManifest,
  type AgentPluginMcpServer,
  type AgentPluginSkill,
  type AgentPluginStdioMcpServer,
  type LoadedAgentPlugin,
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
const MCP_TOP_LEVEL_FIELDS = new Set(["$schema", "mcpServers"]);
const REMOTE_MCP_FIELDS = new Set(["type", "url", "headers"]);
const STDIO_MCP_FIELDS = new Set(["type", "command", "args", "env", "cwd"]);
const HTTP_HEADER_NAME_PATTERN = /^[!#$%&'*+\-.^_`|~0-9A-Za-z]+$/;
const HTTP_HEADER_VALUE_PATTERN = /^[\t\x20-\x7e\x80-\xff]*$/;
const PLUGIN_ROOT_PLACEHOLDER = `\${PLUGIN_ROOT}`;
const PLUGIN_DATA_PLACEHOLDER = `\${PLUGIN_DATA}`;
const MAX_PLUGIN_TEXT_FILE_BYTES = 1024 * 1024;
export const MAX_SKILL_TREE_ENTRIES = 512;
export const MAX_SKILL_TREE_DEPTH = 32;
const FILE_READ_CHUNK_BYTES = 64 * 1024;

class AgentPluginFileTooLargeError extends Error {}

async function readTextFileWithinLimit(filePath: string): Promise<string> {
  const noFollow = fs.constants.O_NOFOLLOW ?? 0;
  const handle = await fs.promises.open(
    filePath,
    fs.constants.O_RDONLY | noFollow,
  );
  try {
    const initialStat = await handle.stat();
    if (!initialStat.isFile()) throw new Error("not a regular file");
    if (initialStat.size > MAX_PLUGIN_TEXT_FILE_BYTES) {
      throw new AgentPluginFileTooLargeError();
    }

    const chunks: Buffer[] = [];
    let bytesRead = 0;
    while (bytesRead <= MAX_PLUGIN_TEXT_FILE_BYTES) {
      const remaining = MAX_PLUGIN_TEXT_FILE_BYTES + 1 - bytesRead;
      const chunk = Buffer.allocUnsafe(
        Math.min(FILE_READ_CHUNK_BYTES, remaining),
      );
      const result = await handle.read(chunk, 0, chunk.byteLength, null);
      if (result.bytesRead === 0) break;
      bytesRead += result.bytesRead;
      if (bytesRead > MAX_PLUGIN_TEXT_FILE_BYTES) {
        throw new AgentPluginFileTooLargeError();
      }
      chunks.push(chunk.subarray(0, result.bytesRead));
    }

    const finalStat = await handle.stat();
    if (
      initialStat.dev !== finalStat.dev ||
      initialStat.ino !== finalStat.ino ||
      initialStat.size !== finalStat.size ||
      initialStat.mtimeMs !== finalStat.mtimeMs ||
      bytesRead !== finalStat.size
    ) {
      throw new Error("file changed while it was read");
    }
    return Buffer.concat(chunks, bytesRead).toString("utf8");
  } finally {
    await handle.close();
  }
}

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isReservedStdioEnvironmentName(name: string): boolean {
  const normalized = process.platform === "win32" ? name.toUpperCase() : name;
  return normalized === "PLUGIN_ROOT" || normalized === "PLUGIN_DATA";
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
  let entryCount = 0;

  const walk = async (
    directory: string,
    depth: number,
  ): Promise<string | null> => {
    if (depth > MAX_SKILL_TREE_DEPTH) {
      return "Skill directories are nested too deeply.";
    }
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
      entryCount += 1;
      if (entryCount > MAX_SKILL_TREE_ENTRIES) {
        return "A skill contains too many files or directories.";
      }
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
        const error = await walk(resolvedEntry, depth + 1);
        if (error) return error;
      } else if (!lstat.isFile()) {
        return "Skill directories can contain only regular files and directories.";
      }
    }
    return null;
  };

  return walk(skillRoot, 0);
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

  const content = await readTextFileWithinLimit(
    path.join(resolvedSkillRoot, "SKILL.md"),
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

      const content = await readTextFileWithinLimit(resolvedSkillMd);
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
    } catch (error) {
      diagnostics.push(
        diagnostic(
          "error",
          "invalid_skill",
          error instanceof AgentPluginFileTooLargeError
            ? `Skipped ${entry.name}: SKILL.md exceeds the 1 MiB limit.`
            : `Skipped ${entry.name}: the skill could not be read.`,
          `skills/${entry.name}`,
        ),
      );
    }
  }
  return skills;
}

function hasOnlyFields(
  value: Record<string, unknown>,
  allowedFields: ReadonlySet<string>,
): boolean {
  return Object.keys(value).every((field) => allowedFields.has(field));
}

function parseHttpHeaders(value: unknown): Record<string, string> | null {
  if (value === undefined) return {};
  if (!isObject(value)) return null;

  const headers: Record<string, string> = {};
  const names = new Set<string>();
  for (const [name, headerValue] of Object.entries(value)) {
    const normalizedName = name.toLowerCase();
    if (
      names.has(normalizedName) ||
      !HTTP_HEADER_NAME_PATTERN.test(name) ||
      typeof headerValue !== "string" ||
      !HTTP_HEADER_VALUE_PATTERN.test(headerValue)
    ) {
      return null;
    }
    names.add(normalizedName);
    headers[name] = headerValue;
  }
  return headers;
}

function isLoopbackHostname(hostname: string): boolean {
  if (hostname === "localhost") return true;
  const unwrappedHostname =
    hostname.startsWith("[") && hostname.endsWith("]")
      ? hostname.slice(1, -1)
      : hostname;
  const ipVersion = net.isIP(unwrappedHostname);
  if (ipVersion === 4) {
    return unwrappedHostname.startsWith("127.");
  }
  return ipVersion === 6 && unwrappedHostname === "::1";
}

function parseRemoteMcpServer(
  serverName: string,
  value: Record<string, unknown>,
): AgentPluginHttpMcpServer | null {
  if (!hasOnlyFields(value, REMOTE_MCP_FIELDS)) return null;
  if (value.type !== "streamable-http" && value.type !== "sse") {
    return null;
  }
  if (typeof value.url !== "string") return null;

  let url: URL;
  try {
    url = new URL(value.url);
  } catch {
    return null;
  }
  if (
    (url.protocol !== "http:" && url.protocol !== "https:") ||
    url.username !== "" ||
    url.password !== "" ||
    url.hash !== "" ||
    (url.protocol === "http:" && !isLoopbackHostname(url.hostname))
  ) {
    return null;
  }

  const headers = parseHttpHeaders(value.headers);
  if (!headers) return null;
  if (value.type === "sse") return null;

  return {
    name: serverName,
    type: "streamable-http",
    url: url.toString(),
    ...(Object.keys(headers).length > 0 ? { headers } : {}),
  };
}

function isContainedPluginPath(pluginRoot: string, value: string): boolean {
  return (
    value.startsWith("./") &&
    isPathContained(pluginRoot, path.resolve(pluginRoot, value))
  );
}

function isValidStdioCwd(pluginRoot: string, value: string): boolean {
  if (value.startsWith("./")) return isContainedPluginPath(pluginRoot, value);
  for (const placeholder of [
    PLUGIN_ROOT_PLACEHOLDER,
    PLUGIN_DATA_PLACEHOLDER,
  ]) {
    if (value === placeholder) return true;
    if (value.startsWith(`${placeholder}/`)) {
      const normalizedValue = path.posix.normalize(
        value.slice(placeholder.length + 1),
      );
      return (
        normalizedValue !== ".." &&
        !normalizedValue.startsWith("../") &&
        !path.posix.isAbsolute(normalizedValue)
      );
    }
  }
  return false;
}

function isValidUnsupportedSseServer(value: Record<string, unknown>): boolean {
  if (value.type !== "sse" || !hasOnlyFields(value, REMOTE_MCP_FIELDS)) {
    return false;
  }
  if (typeof value.url !== "string") return false;
  const headers = parseHttpHeaders(value.headers);
  if (!headers) return false;
  try {
    const url = new URL(value.url);
    return (
      (url.protocol === "http:" || url.protocol === "https:") &&
      url.username === "" &&
      url.password === "" &&
      url.hash === "" &&
      (url.protocol === "https:" || isLoopbackHostname(url.hostname))
    );
  } catch {
    return false;
  }
}

async function parseStdioMcpServer(
  pluginRoot: string,
  serverName: string,
  value: Record<string, unknown>,
): Promise<AgentPluginStdioMcpServer | null> {
  if (value.type !== "stdio" || !hasOnlyFields(value, STDIO_MCP_FIELDS)) {
    return null;
  }
  if (typeof value.command !== "string" || value.command.length === 0) {
    return null;
  }

  const isPluginCommand = value.command.startsWith("./");
  const isBareCommand =
    !value.command.includes("/") &&
    !value.command.includes("\\") &&
    !/\s/.test(value.command);
  if (!isPluginCommand && !isBareCommand) return null;
  if (isPluginCommand) {
    if (!isContainedPluginPath(pluginRoot, value.command)) return null;
    try {
      const commandPath = path.resolve(pluginRoot, value.command);
      const commandLstat = await fs.promises.lstat(commandPath);
      if (commandLstat.isSymbolicLink() || !commandLstat.isFile()) return null;
      const resolvedCommand = await fs.promises.realpath(commandPath);
      if (!isPathContained(pluginRoot, resolvedCommand)) return null;
    } catch {
      return null;
    }
  }

  if (
    value.args !== undefined &&
    (!Array.isArray(value.args) ||
      !value.args.every((argument) => typeof argument === "string"))
  ) {
    return null;
  }
  if (
    value.env !== undefined &&
    (!isObject(value.env) ||
      Object.keys(value.env).some(isReservedStdioEnvironmentName) ||
      !Object.values(value.env).every(
        (environmentValue) => typeof environmentValue === "string",
      ))
  ) {
    return null;
  }
  if (
    value.cwd !== undefined &&
    (typeof value.cwd !== "string" || !isValidStdioCwd(pluginRoot, value.cwd))
  ) {
    return null;
  }

  if (
    typeof value.cwd === "string" &&
    !value.cwd.startsWith(PLUGIN_DATA_PLACEHOLDER)
  ) {
    const relativeCwd = value.cwd.startsWith(PLUGIN_ROOT_PLACEHOLDER)
      ? `.${value.cwd.slice(PLUGIN_ROOT_PLACEHOLDER.length)}`
      : value.cwd;
    try {
      const cwdPath = path.resolve(pluginRoot, relativeCwd);
      const cwdLstat = await fs.promises.lstat(cwdPath);
      if (cwdLstat.isSymbolicLink() || !cwdLstat.isDirectory()) return null;
      const resolvedCwd = await fs.promises.realpath(cwdPath);
      if (!isPathContained(pluginRoot, resolvedCwd)) return null;
    } catch {
      return null;
    }
  }

  return {
    name: serverName,
    type: "stdio",
    command: value.command,
    ...(value.args !== undefined ? { args: value.args as string[] } : {}),
    ...(value.env !== undefined
      ? { env: value.env as Record<string, string> }
      : {}),
    ...(value.cwd !== undefined ? { cwd: value.cwd } : {}),
  };
}

async function loadMcpServers(
  pluginRoot: string,
  diagnostics: AgentPluginDiagnostic[],
): Promise<AgentPluginMcpServer[]> {
  const mcpPath = path.join(pluginRoot, "mcp.json");
  let resolvedMcpPath: string;
  try {
    resolvedMcpPath = await fs.promises.realpath(mcpPath);
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") return [];
    diagnostics.push(
      diagnostic(
        "error",
        "invalid_mcp_config",
        "Could not read mcp.json. MCP servers from this plugin are disabled.",
        "mcp.json",
      ),
    );
    return [];
  }

  if (!isPathContained(pluginRoot, resolvedMcpPath)) {
    diagnostics.push(
      diagnostic(
        "error",
        "mcp_escape",
        "mcp.json resolves outside the plugin directory. MCP servers from this plugin are disabled.",
        "mcp.json",
      ),
    );
    return [];
  }

  let rawMcp: unknown;
  try {
    const stat = await fs.promises.stat(resolvedMcpPath);
    if (!stat.isFile()) throw new Error("not a file");
    rawMcp = JSON.parse(await readTextFileWithinLimit(resolvedMcpPath));
  } catch (error) {
    diagnostics.push(
      diagnostic(
        "error",
        "invalid_mcp_config",
        error instanceof SyntaxError
          ? "mcp.json is not valid JSON. MCP servers from this plugin are disabled."
          : error instanceof AgentPluginFileTooLargeError
            ? "mcp.json exceeds the 1 MiB limit. MCP servers from this plugin are disabled."
            : "mcp.json is not a regular file. MCP servers from this plugin are disabled.",
        "mcp.json",
      ),
    );
    return [];
  }

  if (
    !isObject(rawMcp) ||
    !hasOnlyFields(rawMcp, MCP_TOP_LEVEL_FIELDS) ||
    rawMcp.$schema !== AGENT_PLUGINS_MCP_SCHEMA ||
    !isObject(rawMcp.mcpServers)
  ) {
    diagnostics.push(
      diagnostic(
        "error",
        "invalid_mcp_config",
        `mcp.json must target ${AGENT_PLUGINS_MCP_SCHEMA} and contain only an mcpServers object. MCP servers from this plugin are disabled.`,
        "mcp.json",
      ),
    );
    return [];
  }

  const servers: AgentPluginMcpServer[] = [];
  for (const [serverName, rawServer] of Object.entries(rawMcp.mcpServers).sort(
    ([left], [right]) => left.localeCompare(right),
  )) {
    const serverPath = `mcp.json/mcpServers/${serverName}`;
    if (!isObject(rawServer)) {
      diagnostics.push(
        diagnostic(
          "error",
          "invalid_mcp_server",
          `Skipped MCP server ${serverName} because its configuration is invalid.`,
          serverPath,
        ),
      );
      continue;
    }

    if (rawServer.type === "streamable-http") {
      const server = parseRemoteMcpServer(serverName, rawServer);
      if (server) {
        servers.push(server);
      } else {
        diagnostics.push(
          diagnostic(
            "error",
            "invalid_mcp_server",
            `Skipped MCP server ${serverName} because its Streamable HTTP configuration is invalid.`,
            serverPath,
          ),
        );
      }
      continue;
    }

    if (rawServer.type === "stdio") {
      const server = await parseStdioMcpServer(
        pluginRoot,
        serverName,
        rawServer,
      );
      if (server) {
        servers.push(server);
      } else {
        diagnostics.push(
          diagnostic(
            "error",
            "invalid_mcp_server",
            `Skipped MCP server ${serverName} because its stdio configuration is invalid.`,
            serverPath,
          ),
        );
      }
      continue;
    }

    if (isValidUnsupportedSseServer(rawServer)) {
      diagnostics.push(
        diagnostic(
          "warning",
          "unsupported_mcp_transport",
          `Skipped MCP server ${serverName} because sse transport is not supported.`,
          serverPath,
        ),
      );
      continue;
    }

    diagnostics.push(
      diagnostic(
        "error",
        "invalid_mcp_server",
        `Skipped MCP server ${serverName} because its configuration is invalid.`,
        serverPath,
      ),
    );
  }
  return servers;
}

export async function loadAgentPlugin(
  sourcePath: string,
): Promise<LoadedAgentPlugin> {
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
        mcpServers: [],
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
      mcpServers: [],
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
        mcpServers: [],
        diagnostics,
      };
    }
    const stat = await fs.promises.stat(resolvedManifestPath);
    if (!stat.isFile()) throw new Error("not a file");
    rawManifest = JSON.parse(
      await readTextFileWithinLimit(resolvedManifestPath),
    );
  } catch (error) {
    diagnostics.push(
      diagnostic(
        "error",
        "invalid_manifest",
        error instanceof SyntaxError
          ? "plugin.json is not valid JSON."
          : error instanceof AgentPluginFileTooLargeError
            ? "plugin.json exceeds the 1 MiB limit."
            : "plugin.json is missing or is not a regular file.",
        "plugin.json",
      ),
    );
    return {
      valid: false,
      sourcePath: pluginRoot,
      manifest: null,
      skills: [],
      mcpServers: [],
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
      mcpServers: [],
      diagnostics,
    };
  }

  const [skills, mcpServers] = await Promise.all([
    loadSkills(pluginRoot, diagnostics),
    loadMcpServers(pluginRoot, diagnostics),
  ]);
  return {
    valid: true,
    sourcePath: pluginRoot,
    manifest,
    skills,
    mcpServers,
    diagnostics,
  };
}
