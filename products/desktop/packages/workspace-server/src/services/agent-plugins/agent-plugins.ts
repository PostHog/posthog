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
import { loadAgentPlugin } from "./loader";
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

@injectable()
export class AgentPluginsService {
  private writeQueue: Promise<void> = Promise.resolve();

  constructor(
    @inject(STORAGE_PATHS_SERVICE)
    private readonly storagePaths: IStoragePaths,
    @inject(DIALOG_SERVICE)
    private readonly dialog: IDialog,
  ) {}

  async list(): Promise<AgentPluginInstallation[]> {
    const state = await this.readState();
    const installations = await Promise.all(
      state.installations.map(async (installation) => {
        const preview = await loadAgentPlugin(installation.sourcePath);
        return {
          ...installation,
          sourcePath: preview.sourcePath,
          manifest: preview.manifest ?? installation.manifest,
          skills: preview.valid ? preview.skills : [],
          diagnostics: preview.diagnostics,
        } satisfies AgentPluginInstallation;
      }),
    );
    await this.writeState({ version: 1, installations });
    return installations;
  }

  preview(sourcePath: string): Promise<AgentPluginPreview> {
    return loadAgentPlugin(sourcePath);
  }

  async selectDirectory(): Promise<AgentPluginPreview | null> {
    const [sourcePath] = await this.dialog.pickFile({
      title: "Choose an Agent Plugin directory",
      directories: true,
    });
    return sourcePath ? this.preview(sourcePath) : null;
  }

  async register(sourcePath: string): Promise<AgentPluginInstallation> {
    const preview = await loadAgentPlugin(sourcePath);
    if (!preview.valid || !preview.manifest) {
      throw new Error(
        preview.diagnostics.find((item) => item.severity === "error")
          ?.message ?? "The selected directory is not a valid Agent Plugin.",
      );
    }

    const state = await this.readState();
    const id = this.installationId(preview.sourcePath);
    const existing = state.installations.find(
      (installation) => installation.id === id,
    );
    const installation: AgentPluginInstallation = {
      id,
      sourcePath: preview.sourcePath,
      enabled: existing?.enabled ?? true,
      manifest: preview.manifest,
      skills: preview.skills,
      diagnostics: preview.diagnostics,
    };
    const installations = state.installations.filter(
      (item) => item.id !== installation.id,
    );
    installations.push(installation);
    await this.writeState({ version: 1, installations });
    return installation;
  }

  async setEnabled(
    id: string,
    enabled: boolean,
  ): Promise<AgentPluginInstallation> {
    const state = await this.readState();
    const installation = state.installations.find((item) => item.id === id);
    if (!installation) throw new Error("Agent Plugin installation not found.");
    const updated = { ...installation, enabled };
    await this.writeState({
      version: 1,
      installations: state.installations.map((item) =>
        item.id === id ? updated : item,
      ),
    });
    return updated;
  }

  async unregister(id: string): Promise<void> {
    const state = await this.readState();
    await this.writeState({
      version: 1,
      installations: state.installations.filter((item) => item.id !== id),
    });
  }

  async prepareRuntimePlugins(
    taskRunId: string,
    reservedSkillNames: ReadonlySet<string>,
  ): Promise<RuntimeAgentPlugin[]> {
    if (!isSafePathSegment(taskRunId)) {
      throw new Error(`Unsafe taskRunId: ${JSON.stringify(taskRunId)}`);
    }

    const runtimeRoot = this.runtimeRoot(taskRunId);
    await fs.promises.rm(runtimeRoot, { recursive: true, force: true });
    await fs.promises.mkdir(runtimeRoot, { recursive: true });

    const claimedSkillNames = new Set(reservedSkillNames);
    const state = await this.readState();
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
      if (!preview.valid || !preview.manifest) continue;
      const skills = preview.skills.filter((skill) => {
        if (claimedSkillNames.has(skill.name)) return false;
        claimedSkillNames.add(skill.name);
        return true;
      });
      if (skills.length === 0) continue;

      const pluginPath = path.join(runtimeRoot, installation.id);
      const skillsPath = path.join(pluginPath, "skills");
      await fs.promises.mkdir(skillsPath, { recursive: true });
      await fs.promises.writeFile(
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
        "utf8",
      );
      for (const skill of skills) {
        await fs.promises.symlink(
          skill.path,
          path.join(skillsPath, skill.name),
        );
      }
      plugins.push({ pluginPath, skillsPath });
    }
    return plugins;
  }

  async cleanupRuntimePlugins(taskRunId: string): Promise<void> {
    if (!isSafePathSegment(taskRunId)) return;
    await fs.promises.rm(this.runtimeRoot(taskRunId), {
      recursive: true,
      force: true,
    });
  }

  private statePath(): string {
    return path.join(
      this.storagePaths.appDataPath,
      "agent-plugins",
      "installations.json",
    );
  }

  private runtimeRoot(taskRunId: string): string {
    return path.join(
      this.storagePaths.appDataPath,
      "agent-plugins",
      "runtime",
      taskRunId,
    );
  }

  private installationId(sourcePath: string): string {
    return crypto
      .createHash("sha256")
      .update(sourcePath)
      .digest("hex")
      .slice(0, 16);
  }

  private async readState(): Promise<PersistedState> {
    try {
      const value: unknown = JSON.parse(
        await fs.promises.readFile(this.statePath(), "utf8"),
      );
      const parsed = agentPluginState.safeParse(value);
      return parsed.success ? parsed.data : { version: 1, installations: [] };
    } catch {
      return { version: 1, installations: [] };
    }
  }

  private async writeState(state: PersistedState): Promise<void> {
    const write = async (): Promise<void> => {
      const statePath = this.statePath();
      const temporaryPath = `${statePath}.tmp`;
      await fs.promises.mkdir(path.dirname(statePath), { recursive: true });
      await fs.promises.writeFile(
        temporaryPath,
        `${JSON.stringify(state, null, 2)}\n`,
        "utf8",
      );
      await fs.promises.rename(temporaryPath, statePath);
    };
    this.writeQueue = this.writeQueue.then(write, write);
    await this.writeQueue;
  }
}
