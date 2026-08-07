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

async function resolveContainedDirectory(
  root: string,
  candidate: string,
  create: boolean,
): Promise<string> {
  const absoluteCandidate = path.resolve(candidate);
  if (!isPathContained(root, absoluteCandidate)) {
    throw new Error("The stdio working directory escapes its allowed root.");
  }
  if (create) await fs.promises.mkdir(absoluteCandidate, { recursive: true });
  const resolvedCandidate = await fs.promises.realpath(absoluteCandidate);
  if (!isPathContained(root, resolvedCandidate)) {
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
  const pluginDataParentPath = path.dirname(pluginDataPath);
  await fs.promises.mkdir(pluginDataParentPath, { recursive: true });
  const pluginDataParent = await fs.promises.realpath(pluginDataParentPath);
  await fs.promises.mkdir(pluginDataPath, { recursive: true });
  const pluginData = await fs.promises.realpath(pluginDataPath);
  if (!isPathContained(pluginDataParent, pluginData)) {
    throw new Error("The plugin data directory escapes app-managed storage.");
  }
  await fs.promises.access(pluginData, fs.constants.W_OK);

  let command = server.command;
  if (command.startsWith("./")) {
    command = await fs.promises.realpath(path.resolve(pluginRoot, command));
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
