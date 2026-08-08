import * as fs from "node:fs";
import * as path from "node:path";
import { DEFAULT_INHERITED_ENV_VARS } from "@modelcontextprotocol/sdk/client/stdio.js";
import { isPathContained } from "./loader";
import type { AgentPluginStdioMcpServer } from "./schemas";

const PLUGIN_DATA_PLACEHOLDER = `\${PLUGIN_DATA}`;
const PLACEHOLDER_PATTERN = /\$\{PLUGIN_(ROOT|DATA)\}/g;

export interface ResolvedStdioServer {
  command: string;
  args: string[];
  env: Record<string, string>;
  cwd: string;
  pluginRoot: string;
  pluginData: string;
}

export function expandPluginPlaceholders(
  value: string,
  pluginRoot: string,
  pluginData: string,
): string {
  return value.replace(PLACEHOLDER_PATTERN, (_match, name: string) =>
    name === "ROOT" ? pluginRoot : pluginData,
  );
}

export function isReservedPluginEnvironmentName(
  name: string,
  platform: NodeJS.Platform = process.platform,
): boolean {
  const normalized = platform === "win32" ? name.toUpperCase() : name;
  return normalized === "PLUGIN_ROOT" || normalized === "PLUGIN_DATA";
}

function setEnvironmentValue(
  environment: Record<string, string>,
  name: string,
  value: string,
  platform: NodeJS.Platform,
): void {
  if (platform === "win32") {
    const normalizedName = name.toUpperCase();
    for (const existingName of Object.keys(environment)) {
      if (existingName.toUpperCase() === normalizedName) {
        delete environment[existingName];
      }
    }
  }
  environment[name] = value;
}

function ambientValue(
  ambient: NodeJS.ProcessEnv,
  name: string,
  platform: NodeJS.Platform,
): string | undefined {
  if (platform !== "win32") return ambient[name];
  const entry = Object.entries(ambient).find(
    ([key]) => key.toUpperCase() === name.toUpperCase(),
  );
  return entry?.[1];
}

export function buildStdioEnvironment(
  ambient: NodeJS.ProcessEnv,
  configured: Record<string, string>,
  pluginRoot: string,
  pluginData: string,
  platform: NodeJS.Platform = process.platform,
): Record<string, string> {
  const environment: Record<string, string> = {};
  for (const name of DEFAULT_INHERITED_ENV_VARS) {
    const value = ambientValue(ambient, name, platform);
    if (value !== undefined && !value.startsWith("()")) {
      setEnvironmentValue(environment, name, value, platform);
    }
  }
  for (const [name, value] of Object.entries(configured)) {
    if (isReservedPluginEnvironmentName(name, platform)) continue;
    setEnvironmentValue(
      environment,
      name,
      expandPluginPlaceholders(value, pluginRoot, pluginData),
      platform,
    );
  }
  setEnvironmentValue(environment, "PLUGIN_ROOT", pluginRoot, platform);
  setEnvironmentValue(environment, "PLUGIN_DATA", pluginData, platform);
  return environment;
}

async function createContainedDirectory(
  root: string,
  candidate: string,
): Promise<void> {
  const relativePath = path.relative(root, candidate);
  let currentPath = root;
  for (const segment of relativePath.split(path.sep).filter(Boolean)) {
    currentPath = path.join(currentPath, segment);
    try {
      await fs.promises.mkdir(currentPath);
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code !== "EEXIST") throw error;
    }
    const currentStat = await fs.promises.lstat(currentPath);
    if (currentStat.isSymbolicLink() || !currentStat.isDirectory()) {
      throw new Error(
        "The stdio working directory escapes its allowed root through a symbolic link.",
      );
    }
    const resolvedCurrentPath = await fs.promises.realpath(currentPath);
    if (!isPathContained(root, resolvedCurrentPath)) {
      throw new Error("The stdio working directory escapes its allowed root.");
    }
  }
}

async function resolveContainedDirectory(
  root: string,
  candidate: string,
  create: boolean,
): Promise<string> {
  const absoluteRoot = path.resolve(root);
  const absoluteCandidate = path.resolve(candidate);
  if (!isPathContained(absoluteRoot, absoluteCandidate)) {
    throw new Error("The stdio working directory escapes its allowed root.");
  }
  const resolvedRoot = await fs.promises.realpath(absoluteRoot);
  const candidateWithinResolvedRoot = path.join(
    resolvedRoot,
    path.relative(absoluteRoot, absoluteCandidate),
  );
  if (create) {
    await createContainedDirectory(resolvedRoot, candidateWithinResolvedRoot);
  }
  const candidateStat = await fs.promises.lstat(candidateWithinResolvedRoot);
  if (candidateStat.isSymbolicLink()) {
    throw new Error(
      "The stdio working directory escapes its allowed root through a symbolic link.",
    );
  }
  const resolvedCandidate = await fs.promises.realpath(
    candidateWithinResolvedRoot,
  );
  if (!isPathContained(resolvedRoot, resolvedCandidate)) {
    throw new Error("The stdio working directory escapes its allowed root.");
  }
  const stat = await fs.promises.stat(resolvedCandidate);
  if (!stat.isDirectory()) {
    throw new Error("The stdio working directory is not a directory.");
  }
  return resolvedCandidate;
}

async function resolveWorkingDirectory(
  configuredCwd: string | undefined,
  pluginRoot: string,
  pluginData: string,
): Promise<string> {
  if (configuredCwd === undefined) return pluginRoot;
  const expanded = configuredCwd.startsWith("./")
    ? path.resolve(pluginRoot, configuredCwd)
    : expandPluginPlaceholders(configuredCwd, pluginRoot, pluginData);
  if (
    configuredCwd === PLUGIN_DATA_PLACEHOLDER ||
    configuredCwd.startsWith(`${PLUGIN_DATA_PLACEHOLDER}/`)
  ) {
    return resolveContainedDirectory(pluginData, expanded, true);
  }
  return resolveContainedDirectory(pluginRoot, expanded, false);
}

export async function resolveStdioServer(
  pluginSourcePath: string,
  pluginDataPath: string,
  server: AgentPluginStdioMcpServer,
  ambient: NodeJS.ProcessEnv = process.env,
): Promise<ResolvedStdioServer> {
  const pluginRoot = await fs.promises.realpath(pluginSourcePath);
  const absolutePluginDataPath = path.resolve(pluginDataPath);
  const pluginDataParentPath = path.dirname(absolutePluginDataPath);
  await fs.promises.mkdir(pluginDataParentPath, { recursive: true });
  const pluginDataParent = await fs.promises.realpath(pluginDataParentPath);
  await fs.promises.mkdir(absolutePluginDataPath, { recursive: true });
  const pluginDataStat = await fs.promises.lstat(absolutePluginDataPath);
  if (pluginDataStat.isSymbolicLink() || !pluginDataStat.isDirectory()) {
    throw new Error(
      "The plugin data directory escapes app-managed storage or is unsafe.",
    );
  }
  const pluginData = await fs.promises.realpath(absolutePluginDataPath);
  const expectedPluginData = path.join(
    pluginDataParent,
    path.basename(absolutePluginDataPath),
  );
  if (
    !isPathContained(pluginDataParent, pluginData) ||
    path.resolve(pluginData) !== expectedPluginData
  ) {
    throw new Error("The plugin data directory escapes app-managed storage.");
  }
  await fs.promises.access(pluginData, fs.constants.W_OK);

  let command = server.command;
  if (command.startsWith("./")) {
    const commandPath = path.resolve(pluginRoot, command);
    const commandLstat = await fs.promises.lstat(commandPath);
    if (commandLstat.isSymbolicLink() || !commandLstat.isFile()) {
      throw new Error("The stdio command must be a regular file.");
    }
    command = await fs.promises.realpath(commandPath);
    if (!isPathContained(pluginRoot, command)) {
      throw new Error(
        "The stdio command resolves outside the plugin directory.",
      );
    }
    const stat = await fs.promises.stat(command);
    if (!stat.isFile()) {
      throw new Error("The stdio command is not a regular file.");
    }
  }

  const cwd = await resolveWorkingDirectory(server.cwd, pluginRoot, pluginData);
  const args = (server.args ?? []).map((argument) =>
    expandPluginPlaceholders(argument, pluginRoot, pluginData),
  );
  const env = buildStdioEnvironment(
    ambient,
    server.env ?? {},
    pluginRoot,
    pluginData,
  );
  return { command, args, env, cwd, pluginRoot, pluginData };
}
