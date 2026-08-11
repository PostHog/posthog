import fs from "node:fs/promises";
import path from "node:path";
import { injectable } from "inversify";
import { parse as parseToml } from "smol-toml";
import {
  type CreateEnvironmentInput,
  type Environment,
  environmentSchema,
  slugifyEnvironmentName,
  type UpdateEnvironmentInput,
} from "./schemas";

const ENVIRONMENTS_DIR = ".posthog-code/environments";

function environmentsDir(repoPath: string): string {
  return path.join(repoPath, ENVIRONMENTS_DIR);
}

function tomlString(value: string): string {
  if (value.includes("\n")) {
    return `'''\n${value}'''`;
  }
  return JSON.stringify(value);
}

function serializeEnvironment(env: Environment): string {
  const lines: string[] = [];

  lines.push(`id = ${JSON.stringify(env.id)} # DO NOT EDIT MANUALLY`);
  lines.push(`version = ${env.version}`);
  lines.push("");
  lines.push(`name = ${JSON.stringify(env.name)}`);

  if (env.setup?.script) {
    lines.push("");
    lines.push("[setup]");
    lines.push(`script = ${tomlString(env.setup.script)}`);
  }

  if (env.actions && env.actions.length > 0) {
    for (const action of env.actions) {
      lines.push("");
      lines.push("[[actions]]");
      lines.push(`name = ${JSON.stringify(action.name)}`);
      if (action.icon) {
        lines.push(`icon = ${JSON.stringify(action.icon)}`);
      }
      lines.push(`command = ${tomlString(action.command)}`);
    }
  }

  lines.push("");
  return lines.join("\n");
}

interface ScannedEnvironment {
  filePath: string;
  environment: Environment;
}

@injectable()
export class EnvironmentService {
  private async scanEnvironmentFiles(
    repoPath: string,
  ): Promise<ScannedEnvironment[]> {
    const dir = environmentsDir(repoPath);

    let entries: string[];
    try {
      entries = await fs.readdir(dir);
    } catch {
      return [];
    }

    const results: ScannedEnvironment[] = [];

    for (const entry of entries) {
      if (!entry.endsWith(".toml")) continue;

      const filePath = path.join(dir, entry);
      try {
        const content = await fs.readFile(filePath, "utf-8");
        const parsed = parseToml(content);
        const environment = environmentSchema.parse(parsed);
        results.push({ filePath, environment });
      } catch {}
    }

    return results;
  }

  private async findFileById(
    repoPath: string,
    id: string,
  ): Promise<ScannedEnvironment | null> {
    const files = await this.scanEnvironmentFiles(repoPath);
    return files.find((f) => f.environment.id === id) ?? null;
  }

  private async uniqueFilePath(dir: string, slug: string): Promise<string> {
    let candidate = path.join(dir, `${slug}.toml`);
    let suffix = 2;

    while (true) {
      try {
        await fs.access(candidate);
        candidate = path.join(dir, `${slug}-${suffix}.toml`);
        suffix++;
      } catch {
        return candidate;
      }
    }
  }

  async listEnvironments(repoPath: string): Promise<Environment[]> {
    const files = await this.scanEnvironmentFiles(repoPath);
    return files.map((f) => f.environment);
  }

  async getEnvironment(
    repoPath: string,
    id: string,
  ): Promise<Environment | null> {
    const found = await this.findFileById(repoPath, id);
    return found?.environment ?? null;
  }

  async createEnvironment(
    input: Omit<CreateEnvironmentInput, "repoPath">,
    repoPath: string,
  ): Promise<Environment> {
    const dir = environmentsDir(repoPath);
    await fs.mkdir(dir, { recursive: true });

    const environment: Environment = {
      id: crypto.randomUUID(),
      version: 1,
      name: input.name,
      setup: input.setup,
      actions: input.actions,
    };

    const slug = slugifyEnvironmentName(input.name);
    const filePath = await this.uniqueFilePath(dir, slug || "environment");
    await fs.writeFile(filePath, serializeEnvironment(environment), "utf-8");

    return environment;
  }

  async updateEnvironment(
    input: Omit<UpdateEnvironmentInput, "repoPath">,
    repoPath: string,
  ): Promise<Environment> {
    const found = await this.findFileById(repoPath, input.id);
    if (!found) {
      throw new Error(`Environment not found: ${input.id}`);
    }

    const existing = found.environment;

    const updated: Environment = {
      id: existing.id,
      version: existing.version,
      name: input.name ?? existing.name,
      setup: input.setup !== undefined ? input.setup : existing.setup,
      actions: input.actions !== undefined ? input.actions : existing.actions,
    };

    await fs.writeFile(found.filePath, serializeEnvironment(updated), "utf-8");

    return updated;
  }

  async deleteEnvironment(repoPath: string, id: string): Promise<void> {
    const found = await this.findFileById(repoPath, id);
    if (!found) {
      throw new Error(`Environment not found: ${id}`);
    }
    await fs.unlink(found.filePath);
  }
}
