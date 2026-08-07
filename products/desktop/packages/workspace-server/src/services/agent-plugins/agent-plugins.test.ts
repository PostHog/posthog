import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { AgentPluginsService } from "./agent-plugins";
import { loadAgentPlugin } from "./loader";
import { AGENT_PLUGINS_MANIFEST_SCHEMA } from "./schemas";

let root: string;

async function writePlugin(
  directory: string,
  manifest: Record<string, unknown> = {
    $schema: AGENT_PLUGINS_MANIFEST_SCHEMA,
    name: "example-plugin",
  },
): Promise<void> {
  await fs.promises.mkdir(directory, { recursive: true });
  await fs.promises.writeFile(
    path.join(directory, "plugin.json"),
    JSON.stringify(manifest),
  );
}

async function writeSkill(
  pluginDirectory: string,
  name: string,
  description = "Use this skill for tests.",
): Promise<string> {
  const skillDirectory = path.join(pluginDirectory, "skills", name);
  await fs.promises.mkdir(skillDirectory, { recursive: true });
  await fs.promises.writeFile(
    path.join(skillDirectory, "SKILL.md"),
    `---\nname: ${name}\ndescription: ${description}\n---\n\nInstructions.\n`,
  );
  return skillDirectory;
}

function createService(appDataPath: string): AgentPluginsService {
  return new AgentPluginsService(
    {
      appDataPath,
      logsPath: path.join(appDataPath, "logs"),
      logFolderPath: "",
    },
    { confirm: async () => 0, pickFile: async () => [] },
  );
}

describe("Agent Plugins skills support", () => {
  beforeEach(async () => {
    root = await fs.promises.mkdtemp(path.join(os.tmpdir(), "agent-plugins-"));
  });

  afterEach(async () => {
    await fs.promises.rm(root, { recursive: true, force: true });
  });

  it("reports and ignores the two non-fatal manifest exceptions", async () => {
    const pluginDirectory = path.join(root, "plugin");
    await writePlugin(pluginDirectory, {
      $schema: AGENT_PLUGINS_MANIFEST_SCHEMA,
      name: "example-plugin",
      extensions: "invalid but non-fatal",
      futureField: true,
    });
    await writeSkill(pluginDirectory, "summarize");

    const preview = await loadAgentPlugin(pluginDirectory);

    expect(preview.valid).toBe(true);
    expect(preview.skills.map((skill) => skill.name)).toEqual(["summarize"]);
    expect(preview.diagnostics.map((item) => item.code)).toEqual([
      "unknown_manifest_field",
      "invalid_extensions",
    ]);
  });

  it.each([
    [
      "unsupported schema",
      { $schema: "https://example.com/schema", name: "ok" },
    ],
    [
      "invalid name",
      { $schema: AGENT_PLUGINS_MANIFEST_SCHEMA, name: "Bad Name" },
    ],
    [
      "invalid metadata type",
      { $schema: AGENT_PLUGINS_MANIFEST_SCHEMA, name: "ok", version: 1 },
    ],
    [
      "invalid author field",
      {
        $schema: AGENT_PLUGINS_MANIFEST_SCHEMA,
        name: "ok",
        author: { company: "Example" },
      },
    ],
  ])("rejects a manifest with %s", async (_label, manifest) => {
    const pluginDirectory = path.join(root, "plugin");
    await writePlugin(pluginDirectory, manifest);

    const preview = await loadAgentPlugin(pluginDirectory);

    expect(preview.valid).toBe(false);
    expect(preview.manifest).toBeNull();
    expect(preview.diagnostics.some((item) => item.severity === "error")).toBe(
      true,
    );
  });

  it("isolates invalid skills and does not search nested descendants", async () => {
    const pluginDirectory = path.join(root, "plugin");
    await writePlugin(pluginDirectory);
    await writeSkill(pluginDirectory, "valid-skill");
    await writeSkill(pluginDirectory, "wrong-directory");
    await fs.promises.writeFile(
      path.join(pluginDirectory, "skills", "wrong-directory", "SKILL.md"),
      "---\nname: different-name\ndescription: Invalid.\n---\n",
    );
    await writeSkill(
      path.join(pluginDirectory, "skills", "container"),
      "nested-skill",
    );

    const preview = await loadAgentPlugin(pluginDirectory);

    expect(preview.skills.map((skill) => skill.name)).toEqual(["valid-skill"]);
    expect(preview.diagnostics).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ code: "invalid_skill" }),
      ]),
    );
  });

  it("rejects a skill whose package files escape through a symlink", async () => {
    const pluginDirectory = path.join(root, "plugin");
    const outsideDirectory = path.join(root, "outside");
    await writePlugin(pluginDirectory);
    const skillDirectory = await writeSkill(pluginDirectory, "unsafe-skill");
    await fs.promises.mkdir(outsideDirectory);
    await fs.promises.writeFile(
      path.join(outsideDirectory, "secret.txt"),
      "secret",
    );
    await fs.promises.symlink(
      path.join(outsideDirectory, "secret.txt"),
      path.join(skillDirectory, "reference.txt"),
    );

    const preview = await loadAgentPlugin(pluginDirectory);

    expect(preview.valid).toBe(true);
    expect(preview.skills).toEqual([]);
    expect(preview.diagnostics).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ code: "skill_escape" }),
      ]),
    );
  });

  it("persists stable installation identity and enablement", async () => {
    const pluginDirectory = path.join(root, "plugin");
    const appDataPath = path.join(root, "app-data");
    await writePlugin(pluginDirectory);
    await writeSkill(pluginDirectory, "summarize");
    const service = createService(appDataPath);

    const installed = await service.register(pluginDirectory);
    await service.setEnabled(installed.id, false);
    const restartedService = createService(appDataPath);
    const [persisted] = await restartedService.list();

    expect(persisted).toMatchObject({ id: installed.id, enabled: false });
    expect(persisted.skills.map((skill) => skill.name)).toEqual(["summarize"]);
  });

  it("prepares deterministic shims and preserves reserved skill names", async () => {
    const appDataPath = path.join(root, "app-data");
    const alpha = path.join(root, "alpha");
    const beta = path.join(root, "beta");
    await writePlugin(alpha, {
      $schema: AGENT_PLUGINS_MANIFEST_SCHEMA,
      name: "alpha-plugin",
    });
    await writePlugin(beta, {
      $schema: AGENT_PLUGINS_MANIFEST_SCHEMA,
      name: "beta-plugin",
    });
    await writeSkill(alpha, "shared");
    await writeSkill(alpha, "alpha-only");
    await writeSkill(beta, "shared");
    await writeSkill(beta, "reserved");
    const service = createService(appDataPath);
    await service.register(beta);
    await service.register(alpha);

    const runtime = await service.prepareRuntimePlugins(
      "run-1",
      new Set(["reserved"]),
    );

    expect(runtime).toHaveLength(1);
    expect(await fs.promises.readdir(runtime[0].skillsPath)).toEqual([
      "alpha-only",
      "shared",
    ]);
  });
});
