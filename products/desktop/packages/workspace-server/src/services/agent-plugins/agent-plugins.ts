import * as crypto from "node:crypto";
import * as fs from "node:fs";
import * as path from "node:path";
import { DIALOG_SERVICE, type IDialog } from "@posthog/platform/dialog";
import {
  type IStoragePaths,
  STORAGE_PATHS_SERVICE,
} from "@posthog/platform/storage-paths";
import type { McpServerConnection } from "@posthog/shared";
import { inject, injectable } from "inversify";
import { isSafePathSegment } from "../skills/skill-discovery";
import type { AgentPluginHttpProxy } from "./http-proxy";
import { AGENT_PLUGIN_HTTP_PROXY } from "./identifiers";
import {
  isPathContained,
  loadAgentPlugin,
  validateAgentPluginSkillSnapshot,
} from "./loader";
import {
  AGENT_PLUGIN_INSTALLATION_ID_PATTERN,
  type AgentPluginDiagnostic,
  type AgentPluginHttpMcpServer,
  type AgentPluginInstallation,
  type AgentPluginMcpServerSummary,
  type AgentPluginPreview,
  agentPluginState,
} from "./schemas";

interface RuntimeAgentPlugin {
  pluginPath: string;
  skillsPath: string;
}

interface PersistedState {
  version: 1;
  installations: AgentPluginInstallation[];
}

interface PendingSelection {
  sourcePath: string;
  expiresAt: number;
}

interface SnapshotUsage {
  files: number;
  bytes: number;
}

const SELECTION_TTL_MS = 10 * 60 * 1000;
const MAX_SKILL_SNAPSHOT_FILES = 256;
const MAX_SKILL_SNAPSHOT_FILE_BYTES = 1024 * 1024;
const MAX_SKILL_SNAPSHOT_BYTES = 8 * 1024 * 1024;
const MAX_PLUGIN_SNAPSHOT_FILES = 1024;
const MAX_PLUGIN_SNAPSHOT_BYTES = 32 * 1024 * 1024;
const SNAPSHOT_READ_CHUNK_BYTES = 64 * 1024;

function summarizeMcpServers(
  servers: AgentPluginHttpMcpServer[],
): AgentPluginMcpServerSummary[] {
  return servers.map((server) => ({
    name: server.name,
    type: server.type,
    supported: true,
  }));
}

export function agentPluginRuntimeMcpName(
  installationId: string,
  pluginName: string,
  serverName: string,
): string {
  const pluginSlug = pluginName.replaceAll(".", "-").slice(0, 32);
  const serverHash = crypto
    .createHash("sha256")
    .update(serverName)
    .digest("hex")
    .slice(0, 8);
  return `agent-plugin-${pluginSlug}-${installationId.slice(0, 8)}-${serverHash}`;
}

@injectable()
export class AgentPluginsService {
  private stateQueue: Promise<void> = Promise.resolve();
  private readonly pendingSelections = new Map<string, PendingSelection>();
  private readonly runtimeDiagnostics = new Map<
    string,
    AgentPluginDiagnostic[]
  >();

  constructor(
    @inject(STORAGE_PATHS_SERVICE)
    private readonly storagePaths: IStoragePaths,
    @inject(DIALOG_SERVICE)
    private readonly dialog: IDialog,
    @inject(AGENT_PLUGIN_HTTP_PROXY)
    private readonly httpProxy: AgentPluginHttpProxy,
  ) {}

  list(): Promise<AgentPluginInstallation[]> {
    return this.withStateTransaction(async () => {
      const state = await this.readState();
      const installations = await Promise.all(
        state.installations.map(async (installation) => {
          const preview = await loadAgentPlugin(installation.sourcePath);
          const sourceUnchanged =
            preview.sourcePath === installation.sourcePath;
          return {
            ...installation,
            manifest:
              sourceUnchanged && preview.manifest
                ? preview.manifest
                : installation.manifest,
            skills: sourceUnchanged && preview.valid ? preview.skills : [],
            mcpServers:
              sourceUnchanged && preview.valid
                ? summarizeMcpServers(preview.mcpServers)
                : [],
            diagnostics: [
              ...(sourceUnchanged
                ? preview.diagnostics
                : [
                    ...preview.diagnostics,
                    {
                      severity: "error" as const,
                      code: "source_changed",
                      message:
                        "The Agent Plugin directory changed. Remove it and add it again.",
                    },
                  ]),
              ...(this.runtimeDiagnostics.get(installation.id) ?? []),
            ],
          } satisfies AgentPluginInstallation;
        }),
      );
      await this.writeState({ version: 1, installations });
      return installations;
    });
  }

  async selectDirectory(): Promise<AgentPluginPreview | null> {
    const [sourcePath] = await this.dialog.pickFile({
      title: "Choose an Agent Plugin directory",
      directories: true,
    });
    if (!sourcePath) return null;

    const preview = await loadAgentPlugin(sourcePath);
    const publicPreview: AgentPluginPreview = {
      ...preview,
      mcpServers: summarizeMcpServers(preview.mcpServers),
    };
    if (!preview.valid) return publicPreview;

    const selectionToken = crypto.randomUUID();
    this.pendingSelections.set(selectionToken, {
      sourcePath: preview.sourcePath,
      expiresAt: Date.now() + SELECTION_TTL_MS,
    });
    return { ...publicPreview, selectionToken };
  }

  async register(selectionToken: string): Promise<AgentPluginInstallation> {
    const selection = this.takeSelection(selectionToken);
    const preview = await loadAgentPlugin(selection.sourcePath);
    if (
      !preview.valid ||
      !preview.manifest ||
      preview.sourcePath !== selection.sourcePath
    ) {
      throw new Error(
        preview.sourcePath !== selection.sourcePath
          ? "The selected Agent Plugin directory changed. Choose it again."
          : (preview.diagnostics.find((item) => item.severity === "error")
              ?.message ??
              "The selected directory is not a valid Agent Plugin."),
      );
    }

    const manifest = preview.manifest;
    return this.withStateTransaction(async () => {
      const state = await this.readState();
      const id = this.installationId(preview.sourcePath);
      const existing = state.installations.find(
        (installation) => installation.id === id,
      );
      const installation: AgentPluginInstallation = {
        id,
        sourcePath: preview.sourcePath,
        enabled: existing?.enabled ?? true,
        manifest,
        skills: preview.skills,
        mcpServers: summarizeMcpServers(preview.mcpServers),
        diagnostics: preview.diagnostics,
      };
      const installations = state.installations.filter(
        (item) => item.id !== installation.id,
      );
      installations.push(installation);
      this.runtimeDiagnostics.delete(installation.id);
      await this.writeState({ version: 1, installations });
      return installation;
    });
  }

  setEnabled(id: string, enabled: boolean): Promise<AgentPluginInstallation> {
    return this.withStateTransaction(async () => {
      this.assertInstallationId(id);
      const state = await this.readState();
      const installation = state.installations.find((item) => item.id === id);
      if (!installation)
        throw new Error("Agent Plugin installation not found.");
      const updated = { ...installation, enabled };
      await this.writeState({
        version: 1,
        installations: state.installations.map((item) =>
          item.id === id ? updated : item,
        ),
      });
      if (!enabled) {
        this.runtimeDiagnostics.delete(id);
        this.httpProxy.unregisterInstallation(id);
      }
      return updated;
    });
  }

  unregister(id: string): Promise<void> {
    return this.withStateTransaction(async () => {
      this.assertInstallationId(id);
      const state = await this.readState();
      if (!state.installations.some((item) => item.id === id)) {
        throw new Error("Agent Plugin installation not found.");
      }
      await this.writeState({
        version: 1,
        installations: state.installations.filter((item) => item.id !== id),
      });
      this.runtimeDiagnostics.delete(id);
      this.httpProxy.unregisterInstallation(id);
    });
  }

  async prepareRuntimeMcpServers(
    taskRunId: string,
    reservedServerNames: ReadonlySet<string>,
  ): Promise<McpServerConnection[]> {
    if (!isSafePathSegment(taskRunId)) {
      throw new Error(`Unsafe taskRunId: ${JSON.stringify(taskRunId)}`);
    }

    const claimedServerNames = new Set(reservedServerNames);
    const state = await this.withStateTransaction(() => this.readState());
    const installations = state.installations
      .filter((installation) => installation.enabled)
      .sort(
        (left, right) =>
          left.manifest.name.localeCompare(right.manifest.name) ||
          left.id.localeCompare(right.id),
      );

    const runtimeServers: McpServerConnection[] = [];
    for (const installation of installations) {
      this.runtimeDiagnostics.delete(installation.id);
      const preview = await loadAgentPlugin(installation.sourcePath);
      if (
        !preview.valid ||
        !preview.manifest ||
        preview.sourcePath !== installation.sourcePath
      ) {
        continue;
      }

      for (const server of preview.mcpServers) {
        const runtimeName = agentPluginRuntimeMcpName(
          installation.id,
          preview.manifest.name,
          server.name,
        );
        if (claimedServerNames.has(runtimeName)) {
          this.addRuntimeDiagnostic(installation.id, {
            severity: "error",
            code: "mcp_name_collision",
            message: `Skipped MCP server ${server.name} because its runtime name conflicts with another server.`,
            path: `mcp.json/mcpServers/${server.name}`,
          });
          continue;
        }

        try {
          const url = await this.httpProxy.register({
            id: `${taskRunId}:${runtimeName}`,
            runId: taskRunId,
            installationId: installation.id,
            url: server.url,
            headers: server.headers ?? {},
          });
          claimedServerNames.add(runtimeName);
          runtimeServers.push({
            type: "http",
            name: runtimeName,
            url,
            headers: [],
          });
        } catch {
          this.addRuntimeDiagnostic(installation.id, {
            severity: "error",
            code: "mcp_proxy_failed",
            message: `Skipped MCP server ${server.name} because its local connection could not be prepared.`,
            path: `mcp.json/mcpServers/${server.name}`,
          });
        }
      }
    }
    return runtimeServers;
  }

  async prepareRuntimePlugins(
    taskRunId: string,
    reservedSkillNames: ReadonlySet<string>,
    onSkillSkipped: (pluginName: string, skillName: string) => void = () => {},
  ): Promise<RuntimeAgentPlugin[]> {
    if (!isSafePathSegment(taskRunId)) {
      throw new Error(`Unsafe taskRunId: ${JSON.stringify(taskRunId)}`);
    }

    const runtimeRoot = this.runtimeRoot(taskRunId);
    await this.removeManagedPath(runtimeRoot);
    await this.makeManagedDirectory(runtimeRoot);

    const claimedSkillNames = new Set(reservedSkillNames);
    const state = await this.withStateTransaction(() => this.readState());
    const installations = state.installations
      .filter((installation) => installation.enabled)
      .sort(
        (left, right) =>
          left.manifest.name.localeCompare(right.manifest.name) ||
          left.id.localeCompare(right.id),
      );

    const plugins: RuntimeAgentPlugin[] = [];
    for (const installation of installations) {
      const preview = await loadAgentPlugin(installation.sourcePath);
      if (
        !preview.valid ||
        !preview.manifest ||
        preview.sourcePath !== installation.sourcePath
      )
        continue;
      const availableSkills = preview.skills.filter((skill) => {
        if (claimedSkillNames.has(skill.name)) {
          onSkillSkipped(
            preview.manifest?.name ?? installation.manifest.name,
            skill.name,
          );
          return false;
        }
        claimedSkillNames.add(skill.name);
        return true;
      });
      if (availableSkills.length === 0) continue;

      const pluginPath = path.join(runtimeRoot, installation.id);
      const skillsPath = path.join(pluginPath, "skills");
      await this.makeManagedDirectory(skillsPath);
      const copiedSkillNames: string[] = [];
      const pluginUsage: SnapshotUsage = { files: 0, bytes: 0 };
      for (const skill of availableSkills) {
        const destination = path.join(skillsPath, skill.name);
        try {
          const skillUsage = await this.copySkillSnapshot(
            installation.sourcePath,
            skill.path,
            destination,
            pluginUsage,
          );
          const snapshotError = await validateAgentPluginSkillSnapshot(
            pluginPath,
            destination,
            skill.name,
          );
          if (snapshotError) throw new Error(snapshotError);
          pluginUsage.files += skillUsage.files;
          pluginUsage.bytes += skillUsage.bytes;
          copiedSkillNames.push(skill.name);
        } catch {
          await this.removeManagedPath(destination);
          onSkillSkipped(preview.manifest.name, skill.name);
        }
      }
      if (copiedSkillNames.length === 0) {
        await this.removeManagedPath(pluginPath);
        continue;
      }

      await this.writeManagedFile(
        path.join(pluginPath, "plugin.json"),
        `${JSON.stringify({
          name: preview.manifest.name,
          ...(preview.manifest.version
            ? { version: preview.manifest.version }
            : {}),
          ...(preview.manifest.description
            ? { description: preview.manifest.description }
            : {}),
        })}\n`,
      );
      plugins.push({ pluginPath, skillsPath });
    }
    return plugins;
  }

  async cleanupRuntimePlugins(taskRunId: string): Promise<void> {
    if (!isSafePathSegment(taskRunId)) return;
    this.httpProxy.unregisterRun(taskRunId);
    await this.removeManagedPath(this.runtimeRoot(taskRunId));
  }

  private addRuntimeDiagnostic(
    installationId: string,
    diagnostic: AgentPluginDiagnostic,
  ): void {
    const diagnostics = this.runtimeDiagnostics.get(installationId) ?? [];
    diagnostics.push(diagnostic);
    this.runtimeDiagnostics.set(installationId, diagnostics);
  }

  private takeSelection(selectionToken: string): PendingSelection {
    const selection = this.pendingSelections.get(selectionToken);
    this.pendingSelections.delete(selectionToken);
    if (!selection || selection.expiresAt < Date.now()) {
      throw new Error("Choose the Agent Plugin directory again.");
    }
    return selection;
  }

  private withStateTransaction<T>(operation: () => Promise<T>): Promise<T> {
    const result = this.stateQueue.then(operation, operation);
    this.stateQueue = result.then(
      () => undefined,
      () => undefined,
    );
    return result;
  }

  private managedRoot(): string {
    return path.resolve(this.storagePaths.appDataPath, "agent-plugins");
  }

  private statePath(): string {
    return path.join(this.managedRoot(), "installations.json");
  }

  private runtimeRoot(taskRunId: string): string {
    return path.join(this.managedRoot(), "runtime", taskRunId);
  }

  private assertInstallationId(id: string): void {
    if (!AGENT_PLUGIN_INSTALLATION_ID_PATTERN.test(id)) {
      throw new Error("Invalid Agent Plugin installation ID.");
    }
  }

  private installationId(sourcePath: string): string {
    return crypto
      .createHash("sha256")
      .update(sourcePath)
      .digest("hex")
      .slice(0, 16);
  }

  private async readState(): Promise<PersistedState> {
    let raw: string;
    try {
      raw = await fs.promises.readFile(this.statePath(), "utf8");
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code === "ENOENT") {
        return { version: 1, installations: [] };
      }
      throw error;
    }

    let value: unknown;
    try {
      value = JSON.parse(raw);
    } catch {
      throw new Error("Agent Plugin installation data is invalid.");
    }
    const parsed = agentPluginState.safeParse(value);
    if (!parsed.success) {
      throw new Error("Agent Plugin installation data is invalid.");
    }

    const ids = new Set<string>();
    for (const installation of parsed.data.installations) {
      if (
        !path.isAbsolute(installation.sourcePath) ||
        path.normalize(installation.sourcePath) !== installation.sourcePath ||
        this.installationId(installation.sourcePath) !== installation.id ||
        ids.has(installation.id)
      ) {
        throw new Error("Agent Plugin installation data is invalid.");
      }
      ids.add(installation.id);
    }
    return parsed.data;
  }

  private async writeState(state: PersistedState): Promise<void> {
    const statePath = await this.assertManagedPath(this.statePath());
    const temporaryPath = await this.assertManagedPath(`${statePath}.tmp`);
    await this.makeManagedDirectory(path.dirname(statePath));
    await this.writeManagedFile(
      temporaryPath,
      `${JSON.stringify(state, null, 2)}\n`,
    );
    await this.assertManagedPath(statePath);
    await this.assertManagedPath(temporaryPath);
    await fs.promises.rename(temporaryPath, statePath);
  }

  private async copySkillSnapshot(
    pluginRoot: string,
    sourceRoot: string,
    destinationRoot: string,
    pluginUsage: SnapshotUsage,
  ): Promise<SnapshotUsage> {
    const resolvedPluginRoot = await fs.promises.realpath(pluginRoot);
    const pluginRootStat = await fs.promises.lstat(resolvedPluginRoot);
    const resolvedSourceRoot = await fs.promises.realpath(sourceRoot);
    if (
      !pluginRootStat.isDirectory() ||
      !isPathContained(resolvedPluginRoot, resolvedSourceRoot)
    ) {
      throw new Error("Skill path escaped the plugin directory.");
    }

    const skillUsage: SnapshotUsage = { files: 0, bytes: 0 };
    const copyEntry = async (
      source: string,
      destination: string,
    ): Promise<void> => {
      const sourceStat = await fs.promises.lstat(source);
      if (sourceStat.isSymbolicLink()) {
        throw new Error("Skill snapshots do not follow symbolic links.");
      }
      const resolvedSource = await fs.promises.realpath(source);
      if (!isPathContained(resolvedPluginRoot, resolvedSource)) {
        throw new Error("Skill path escaped the plugin directory.");
      }

      if (sourceStat.isDirectory()) {
        await this.makeManagedDirectory(destination);
        const entries = await fs.promises.readdir(source);
        const currentStat = await fs.promises.lstat(source);
        if (!this.hasSameSnapshotMetadata(sourceStat, currentStat)) {
          throw new Error("Skill directory changed while it was copied.");
        }
        for (const entry of entries.sort()) {
          await copyEntry(
            path.join(source, entry),
            path.join(destination, entry),
          );
        }
        const finalStat = await fs.promises.lstat(source);
        if (!this.hasSameSnapshotMetadata(sourceStat, finalStat)) {
          throw new Error("Skill directory changed while it was copied.");
        }
        return;
      }
      if (!sourceStat.isFile()) {
        throw new Error("Skill snapshots contain only regular files.");
      }
      if (sourceStat.size > MAX_SKILL_SNAPSHOT_FILE_BYTES) {
        throw new Error("A skill file exceeds the snapshot size limit.");
      }

      const noFollow = fs.constants.O_NOFOLLOW ?? 0;
      const handle = await fs.promises.open(
        source,
        fs.constants.O_RDONLY | noFollow,
      );
      try {
        const openedStat = await handle.stat();
        if (
          !openedStat.isFile() ||
          !this.hasSameFileIdentity(sourceStat, openedStat)
        ) {
          throw new Error("Skill file changed before it was copied.");
        }
        if (openedStat.size > MAX_SKILL_SNAPSHOT_FILE_BYTES) {
          throw new Error("A skill file exceeds the snapshot size limit.");
        }

        const nextSkillFiles = skillUsage.files + 1;
        const nextPluginFiles = pluginUsage.files + nextSkillFiles;
        if (
          nextSkillFiles > MAX_SKILL_SNAPSHOT_FILES ||
          nextPluginFiles > MAX_PLUGIN_SNAPSHOT_FILES
        ) {
          throw new Error("A skill contains too many snapshot files.");
        }

        const content = await this.readSnapshotFile(handle);
        const nextSkillBytes = skillUsage.bytes + content.byteLength;
        const nextPluginBytes = pluginUsage.bytes + nextSkillBytes;
        if (
          nextSkillBytes > MAX_SKILL_SNAPSHOT_BYTES ||
          nextPluginBytes > MAX_PLUGIN_SNAPSHOT_BYTES
        ) {
          throw new Error("A skill exceeds the snapshot size limit.");
        }

        const finalStat = await handle.stat();
        if (
          !this.hasSameFileIdentity(sourceStat, finalStat) ||
          finalStat.size !== sourceStat.size ||
          finalStat.mtimeMs !== sourceStat.mtimeMs ||
          content.byteLength !== finalStat.size
        ) {
          throw new Error("Skill file changed while it was copied.");
        }

        await this.writeManagedFile(
          destination,
          content,
          openedStat.mode & 0o777,
        );
        skillUsage.files = nextSkillFiles;
        skillUsage.bytes = nextSkillBytes;
      } finally {
        await handle.close();
      }
    };

    await copyEntry(resolvedSourceRoot, destinationRoot);
    const finalPluginRootStat = await fs.promises.lstat(resolvedPluginRoot);
    if (!this.hasSameSnapshotMetadata(pluginRootStat, finalPluginRootStat)) {
      throw new Error("Agent Plugin directory changed while it was copied.");
    }
    return skillUsage;
  }

  private hasSameFileIdentity(left: fs.Stats, right: fs.Stats): boolean {
    return (
      left.dev === right.dev &&
      left.ino === right.ino &&
      left.mode === right.mode
    );
  }

  private hasSameSnapshotMetadata(left: fs.Stats, right: fs.Stats): boolean {
    return (
      this.hasSameFileIdentity(left, right) &&
      left.size === right.size &&
      left.mtimeMs === right.mtimeMs
    );
  }

  private async readSnapshotFile(
    handle: fs.promises.FileHandle,
  ): Promise<Buffer> {
    const chunks: Buffer[] = [];
    let bytesRead = 0;
    while (bytesRead <= MAX_SKILL_SNAPSHOT_FILE_BYTES) {
      const remaining = MAX_SKILL_SNAPSHOT_FILE_BYTES + 1 - bytesRead;
      const chunk = Buffer.allocUnsafe(
        Math.min(SNAPSHOT_READ_CHUNK_BYTES, remaining),
      );
      const result = await handle.read(chunk, 0, chunk.byteLength, null);
      if (result.bytesRead === 0) break;
      bytesRead += result.bytesRead;
      if (bytesRead > MAX_SKILL_SNAPSHOT_FILE_BYTES) {
        throw new Error("A skill file exceeds the snapshot size limit.");
      }
      chunks.push(chunk.subarray(0, result.bytesRead));
    }
    return Buffer.concat(chunks, bytesRead);
  }

  private async ensureManagedRoot(): Promise<string> {
    const root = this.managedRoot();
    try {
      const existing = await fs.promises.lstat(root);
      if (existing.isSymbolicLink() || !existing.isDirectory()) {
        throw new Error("Agent Plugin storage root is unsafe.");
      }
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw error;
      await fs.promises.mkdir(root, { recursive: true });
      const created = await fs.promises.lstat(root);
      if (created.isSymbolicLink() || !created.isDirectory()) {
        throw new Error("Agent Plugin storage root is unsafe.");
      }
    }
    return fs.promises.realpath(root);
  }

  private async assertManagedPath(candidate: string): Promise<string> {
    const root = this.managedRoot();
    const absoluteCandidate = path.resolve(candidate);
    if (!isPathContained(root, absoluteCandidate)) {
      throw new Error("Agent Plugin storage path is unsafe.");
    }

    const resolvedRoot = await this.ensureManagedRoot();
    const relative = path.relative(root, absoluteCandidate);
    let current = root;
    for (const segment of relative.split(path.sep).filter(Boolean)) {
      current = path.join(current, segment);
      try {
        const stat = await fs.promises.lstat(current);
        if (stat.isSymbolicLink()) {
          throw new Error("Agent Plugin storage path is unsafe.");
        }
        const resolvedCurrent = await fs.promises.realpath(current);
        if (!isPathContained(resolvedRoot, resolvedCurrent)) {
          throw new Error("Agent Plugin storage path is unsafe.");
        }
      } catch (error) {
        if ((error as NodeJS.ErrnoException).code === "ENOENT") break;
        throw error;
      }
    }
    return absoluteCandidate;
  }

  private async makeManagedDirectory(directory: string): Promise<void> {
    const safeDirectory = await this.assertManagedPath(directory);
    await fs.promises.mkdir(safeDirectory, { recursive: true });
    await this.assertManagedPath(safeDirectory);
  }

  private async writeManagedFile(
    filePath: string,
    content: string | Uint8Array,
    mode?: number,
  ): Promise<void> {
    const safePath = await this.assertManagedPath(filePath);
    await this.makeManagedDirectory(path.dirname(safePath));
    await this.assertManagedPath(safePath);
    await fs.promises.writeFile(safePath, content, {
      ...(mode === undefined ? {} : { mode }),
    });
  }

  private async removeManagedPath(target: string): Promise<void> {
    const safeTarget = await this.assertManagedPath(target);
    if (safeTarget === this.managedRoot()) {
      throw new Error("Agent Plugin storage root cannot be removed.");
    }
    await fs.promises.rm(safeTarget, { recursive: true, force: true });
  }
}
