import * as crypto from "node:crypto";
import * as fs from "node:fs";
import * as path from "node:path";
import { DIALOG_SERVICE, type IDialog } from "@posthog/platform/dialog";
import {
  type IStoragePaths,
  STORAGE_PATHS_SERVICE,
} from "@posthog/platform/storage-paths";
import { inject, injectable } from "inversify";
import { isSafePathSegment } from "../skills/skill-discovery";
import { isPathContained, loadAgentPlugin } from "./loader";
import {
  type AgentPluginInstallation,
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

const SELECTION_TTL_MS = 10 * 60 * 1000;

@injectable()
export class AgentPluginsService {
  private stateQueue: Promise<void> = Promise.resolve();
  private readonly pendingSelections = new Map<string, PendingSelection>();

  constructor(
    @inject(STORAGE_PATHS_SERVICE)
    private readonly storagePaths: IStoragePaths,
    @inject(DIALOG_SERVICE)
    private readonly dialog: IDialog,
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
            diagnostics: sourceUnchanged
              ? preview.diagnostics
              : [
                  ...preview.diagnostics,
                  {
                    severity: "error",
                    code: "source_changed",
                    message:
                      "The Agent Plugin directory changed. Remove it and add it again.",
                  },
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
    if (!preview.valid) return preview;

    const selectionToken = crypto.randomUUID();
    this.pendingSelections.set(selectionToken, {
      sourcePath: preview.sourcePath,
      expiresAt: Date.now() + SELECTION_TTL_MS,
    });
    return { ...preview, selectionToken };
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
        diagnostics: preview.diagnostics,
      };
      const installations = state.installations.filter(
        (item) => item.id !== installation.id,
      );
      installations.push(installation);
      await this.writeState({ version: 1, installations });
      return installation;
    });
  }

  setEnabled(id: string, enabled: boolean): Promise<AgentPluginInstallation> {
    return this.withStateTransaction(async () => {
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
      return updated;
    });
  }

  unregister(id: string): Promise<void> {
    return this.withStateTransaction(async () => {
      const state = await this.readState();
      await this.writeState({
        version: 1,
        installations: state.installations.filter((item) => item.id !== id),
      });
    });
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
      for (const skill of availableSkills) {
        const destination = path.join(skillsPath, skill.name);
        try {
          await this.copySkillSnapshot(
            installation.sourcePath,
            skill.path,
            destination,
          );
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
    await this.removeManagedPath(this.runtimeRoot(taskRunId));
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
  ): Promise<void> {
    const resolvedPluginRoot = await fs.promises.realpath(pluginRoot);
    const resolvedSourceRoot = await fs.promises.realpath(sourceRoot);
    if (!isPathContained(resolvedPluginRoot, resolvedSourceRoot)) {
      throw new Error("Skill path escaped the plugin directory.");
    }

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
        for (const entry of entries.sort()) {
          await copyEntry(
            path.join(source, entry),
            path.join(destination, entry),
          );
        }
        return;
      }
      if (!sourceStat.isFile()) {
        throw new Error("Skill snapshots contain only regular files.");
      }

      const noFollow = fs.constants.O_NOFOLLOW ?? 0;
      const handle = await fs.promises.open(
        source,
        fs.constants.O_RDONLY | noFollow,
      );
      try {
        const openedStat = await handle.stat();
        if (!openedStat.isFile()) {
          throw new Error("Skill snapshots contain only regular files.");
        }
        const content = await handle.readFile();
        await this.writeManagedFile(
          destination,
          content,
          openedStat.mode & 0o777,
        );
      } finally {
        await handle.close();
      }
    };

    await copyEntry(resolvedSourceRoot, destinationRoot);
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
    await fs.promises.rm(safeTarget, { recursive: true, force: true });
  }
}
