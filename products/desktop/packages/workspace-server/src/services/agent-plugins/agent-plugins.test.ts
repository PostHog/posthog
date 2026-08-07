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

function createService(
  appDataPath: string,
  selectedPaths: string[] = [],
): AgentPluginsService {
  return new AgentPluginsService(
    {
      appDataPath,
      logsPath: path.join(appDataPath, "logs"),
      logFolderPath: "",
    },
    {
      confirm: async () => 0,
      pickFile: async () => {
        const selectedPath = selectedPaths.shift();
        return selectedPath ? [selectedPath] : [];
      },
    },
  );
}

async function registerSelectedPlugin(
  service: AgentPluginsService,
): Promise<Awaited<ReturnType<AgentPluginsService["register"]>>> {
  const preview = await service.selectDirectory();
  if (!preview?.selectionToken) {
    throw new Error("Expected a valid selected plugin");
  }
  return service.register(preview.selectionToken);
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
    const service = createService(appDataPath, [pluginDirectory]);

    const installed = await registerSelectedPlugin(service);
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
    const service = createService(appDataPath, [beta, alpha]);
    await registerSelectedPlugin(service);
    await registerSelectedPlugin(service);

    const skipped: string[] = [];
    const runtime = await service.prepareRuntimePlugins(
      "run-1",
      new Set(["reserved"]),
      (pluginName, skillName) => skipped.push(`${pluginName}:${skillName}`),
    );

    expect(runtime).toHaveLength(1);
    expect(skipped).toEqual(["beta-plugin:reserved", "beta-plugin:shared"]);
    expect(await fs.promises.readdir(runtime[0].skillsPath)).toEqual([
      "alpha-only",
      "shared",
    ]);
  });

  it("snapshots regular skill files instead of linking mutable sources", async () => {
    const appDataPath = path.join(root, "app-data");
    const pluginDirectory = path.join(root, "plugin");
    await writePlugin(pluginDirectory);
    const sourceSkill = await writeSkill(pluginDirectory, "summarize");
    const service = createService(appDataPath, [pluginDirectory]);
    await registerSelectedPlugin(service);

    const [runtime] = await service.prepareRuntimePlugins("run-1", new Set());
    const snapshotSkill = path.join(runtime.skillsPath, "summarize");
    const original = await fs.promises.readFile(
      path.join(snapshotSkill, "SKILL.md"),
      "utf8",
    );
    expect((await fs.promises.lstat(snapshotSkill)).isDirectory()).toBe(true);
    expect((await fs.promises.lstat(snapshotSkill)).isSymbolicLink()).toBe(
      false,
    );

    await fs.promises.writeFile(
      path.join(sourceSkill, "SKILL.md"),
      "changed after validation",
    );
    await fs.promises.symlink(
      path.join(root, "outside.txt"),
      path.join(sourceSkill, "outside.txt"),
    );

    expect(
      await fs.promises.readFile(path.join(snapshotSkill, "SKILL.md"), "utf8"),
    ).toBe(original);
    await expect(
      fs.promises.lstat(path.join(snapshotSkill, "outside.txt")),
    ).rejects.toMatchObject({ code: "ENOENT" });
  });

  it("serializes removal and enablement without resurrecting an installation", async () => {
    const appDataPath = path.join(root, "app-data");
    const pluginDirectory = path.join(root, "plugin");
    await writePlugin(pluginDirectory);
    await writeSkill(pluginDirectory, "summarize");
    const service = createService(appDataPath, [pluginDirectory]);
    const installed = await registerSelectedPlugin(service);

    const outcomes = await Promise.allSettled([
      service.unregister(installed.id),
      service.setEnabled(installed.id, false),
    ]);

    expect(outcomes.map((outcome) => outcome.status)).toEqual([
      "fulfilled",
      "rejected",
    ]);
    expect(await service.list()).toEqual([]);
  });

  it("rejects tampered persisted identities before managed path operations", async () => {
    const appDataPath = path.join(root, "app-data");
    const pluginDirectory = path.join(root, "plugin");
    await writePlugin(pluginDirectory);
    await writeSkill(pluginDirectory, "summarize");
    const service = createService(appDataPath, [pluginDirectory]);
    await registerSelectedPlugin(service);
    const statePath = path.join(
      appDataPath,
      "agent-plugins",
      "installations.json",
    );
    const originalState = JSON.parse(
      await fs.promises.readFile(statePath, "utf8"),
    ) as { installations: Array<Record<string, unknown>> };
    const invalidStates = [
      {
        ...originalState,
        installations: [
          { ...originalState.installations[0], id: "../outside" },
        ],
      },
      {
        ...originalState,
        installations: [
          { ...originalState.installations[0], id: "0000000000000000" },
        ],
      },
      {
        ...originalState,
        installations: [
          originalState.installations[0],
          originalState.installations[0],
        ],
      },
    ];
    const outsideMarker = path.join(root, "outside-marker");
    await fs.promises.writeFile(outsideMarker, "keep");

    for (const invalidState of invalidStates) {
      await fs.promises.writeFile(statePath, JSON.stringify(invalidState));
      await expect(service.list()).rejects.toThrow(
        "Agent Plugin installation data is invalid",
      );
      await expect(
        service.prepareRuntimePlugins("run-1", new Set()),
      ).rejects.toThrow("Agent Plugin installation data is invalid");
      expect(await fs.promises.readFile(outsideMarker, "utf8")).toBe("keep");
    }
  });

  it("requires a one-time native directory selection before registration", async () => {
    const appDataPath = path.join(root, "app-data");
    const pluginDirectory = path.join(root, "plugin");
    await writePlugin(pluginDirectory);
    await writeSkill(pluginDirectory, "summarize");
    const service = createService(appDataPath, [pluginDirectory]);

    await expect(service.register(pluginDirectory)).rejects.toThrow(
      "Choose the Agent Plugin directory again",
    );
    const preview = await service.selectDirectory();
    expect(preview?.selectionToken).toBeTypeOf("string");
    const installed = await service.register(preview?.selectionToken ?? "");
    expect(installed.sourcePath).toBe(
      await fs.promises.realpath(pluginDirectory),
    );
    await expect(
      service.register(preview?.selectionToken ?? ""),
    ).rejects.toThrow("Choose the Agent Plugin directory again");
  });
});
