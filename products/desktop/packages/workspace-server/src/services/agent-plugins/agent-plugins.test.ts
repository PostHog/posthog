import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
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

async function writeSparseFile(filePath: string, size: number): Promise<void> {
  const handle = await fs.promises.open(filePath, "w");
  try {
    await handle.truncate(size);
  } finally {
    await handle.close();
  }
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
    vi.restoreAllMocks();
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

  it.each([
    [
      "plugin.json",
      async (pluginDirectory: string, _skillDirectory: string) => {
        await writeSparseFile(
          path.join(pluginDirectory, "plugin.json"),
          1024 * 1024 + 1,
        );
      },
      false,
    ],
    [
      "SKILL.md",
      async (_pluginDirectory: string, skillDirectory: string) => {
        await writeSparseFile(
          path.join(skillDirectory, "SKILL.md"),
          1024 * 1024 + 1,
        );
      },
      true,
    ],
  ])(
    "rejects an oversized %s before parsing it",
    async (_label, addPayload, manifestRemainsValid) => {
      const pluginDirectory = path.join(root, "plugin");
      await writePlugin(pluginDirectory);
      const skillDirectory = await writeSkill(pluginDirectory, "summarize");
      await addPayload(pluginDirectory, skillDirectory);

      const preview = await loadAgentPlugin(pluginDirectory);

      expect(preview.valid).toBe(manifestRemainsValid);
      expect(preview.skills).toEqual([]);
      expect(preview.diagnostics).toEqual(
        expect.arrayContaining([
          expect.objectContaining({
            code: manifestRemainsValid ? "invalid_skill" : "invalid_manifest",
          }),
        ]),
      );
    },
  );

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

  it.each([
    [
      "entry count",
      async (skillDirectory: string) => {
        await Promise.all(
          Array.from({ length: 512 }, (_, index) =>
            fs.promises.mkdir(path.join(skillDirectory, `directory-${index}`)),
          ),
        );
      },
      "too many files or directories",
    ],
    [
      "directory depth",
      async (skillDirectory: string) => {
        let nestedDirectory = skillDirectory;
        for (let depth = 0; depth < 33; depth += 1) {
          nestedDirectory = path.join(nestedDirectory, "d");
          await fs.promises.mkdir(nestedDirectory);
        }
      },
      "nested too deeply",
    ],
  ])(
    "rejects a skill that exceeds the tree %s limit",
    async (_label, addPayload, expectedMessage) => {
      const pluginDirectory = path.join(root, "plugin");
      await writePlugin(pluginDirectory);
      const skillDirectory = await writeSkill(pluginDirectory, "summarize");
      await addPayload(skillDirectory);

      const preview = await loadAgentPlugin(pluginDirectory);

      expect(preview.valid).toBe(true);
      expect(preview.skills).toEqual([]);
      expect(preview.diagnostics).toEqual(
        expect.arrayContaining([
          expect.objectContaining({
            code: "skill_escape",
            message: expect.stringContaining(expectedMessage),
          }),
        ]),
      );
    },
  );

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

  it("skips all skills when the skills directory disappears after discovery", async () => {
    const pluginDirectory = path.join(root, "plugin");
    const skillsDirectory = path.join(pluginDirectory, "skills");
    await writePlugin(pluginDirectory);
    await writeSkill(pluginDirectory, "summarize");
    const originalStat = fs.promises.stat.bind(fs.promises);
    vi.spyOn(fs.promises, "stat").mockImplementation(
      async (target, options) => {
        if (String(target).endsWith(path.join("plugin", "skills"))) {
          await fs.promises.rm(skillsDirectory, { recursive: true });
        }
        return originalStat(target, options);
      },
    );

    const preview = await loadAgentPlugin(pluginDirectory);

    expect(preview.valid).toBe(true);
    expect(preview.skills).toEqual([]);
    expect(preview.diagnostics).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ code: "invalid_skills" }),
      ]),
    );
  });

  it("skips all skills when the skills directory cannot be listed", async () => {
    const pluginDirectory = path.join(root, "plugin");
    const _skillsDirectory = path.join(pluginDirectory, "skills");
    await writePlugin(pluginDirectory);
    await writeSkill(pluginDirectory, "summarize");
    const originalReaddir = fs.promises.readdir.bind(fs.promises);
    vi.spyOn(fs.promises, "readdir").mockImplementation(
      async (target, options) => {
        if (String(target).endsWith(path.join("plugin", "skills"))) {
          throw Object.assign(new Error("denied"), { code: "EACCES" });
        }
        return originalReaddir(target, options);
      },
    );

    const preview = await loadAgentPlugin(pluginDirectory);

    expect(preview.valid).toBe(true);
    expect(preview.skills).toEqual([]);
    expect(preview.diagnostics).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ code: "invalid_skills" }),
      ]),
    );
  });

  it("skips a skill when its file identity changes before opening", async () => {
    const appDataPath = path.join(root, "app-data");
    const pluginDirectory = path.join(root, "plugin");
    const skillDirectory = await writeSkill(pluginDirectory, "summarize");
    await writePlugin(pluginDirectory);
    const referencePath = path.join(skillDirectory, "reference.txt");
    await fs.promises.writeFile(referencePath, "original");
    const service = createService(appDataPath, [pluginDirectory]);
    await registerSelectedPlugin(service);
    const originalOpen = fs.promises.open.bind(fs.promises);
    let replaced = false;
    vi.spyOn(fs.promises, "open").mockImplementation(
      async (target, flags, mode) => {
        if (
          String(target).endsWith(
            path.join("skills", "summarize", "reference.txt"),
          ) &&
          !replaced
        ) {
          replaced = true;
          await fs.promises.rename(referencePath, `${referencePath}.old`);
          await fs.promises.writeFile(referencePath, "replacement");
        }
        return originalOpen(target, flags, mode);
      },
    );
    const skipped: string[] = [];

    const runtime = await service.prepareRuntimePlugins(
      "run-identity",
      new Set(),
      (_pluginName, skillName) => skipped.push(skillName),
    );

    expect(runtime).toEqual([]);
    expect(skipped).toEqual(["summarize"]);
  });

  it("validates the completed snapshot when a source changes before file copying", async () => {
    const appDataPath = path.join(root, "app-data");
    const pluginDirectory = path.join(root, "plugin");
    await writePlugin(pluginDirectory);
    const skillDirectory = await writeSkill(pluginDirectory, "summarize");
    const service = createService(appDataPath, [pluginDirectory]);
    await registerSelectedPlugin(service);
    const originalMkdir = fs.promises.mkdir.bind(fs.promises);
    let changed = false;
    vi.spyOn(fs.promises, "mkdir").mockImplementation(
      async (target, options) => {
        const result = await originalMkdir(target, options);
        if (
          String(target).includes(path.join("runtime", "run-postvalidate")) &&
          String(target).endsWith(path.join("skills", "summarize")) &&
          !changed
        ) {
          changed = true;
          await fs.promises.writeFile(
            path.join(skillDirectory, "SKILL.md"),
            "content without frontmatter",
          );
        }
        return result;
      },
    );
    const skipped: string[] = [];

    const runtime = await service.prepareRuntimePlugins(
      "run-postvalidate",
      new Set(),
      (_pluginName, skillName) => skipped.push(skillName),
    );

    expect(runtime).toEqual([]);
    expect(skipped).toEqual(["summarize"]);
  });

  it("removes partial runtime snapshots when preparation fails", async () => {
    const appDataPath = path.join(root, "app-data");
    const pluginDirectory = path.join(root, "plugin");
    await writePlugin(pluginDirectory);
    await writeSkill(pluginDirectory, "summarize");
    const service = createService(appDataPath, [pluginDirectory]);
    await registerSelectedPlugin(service);
    const originalWriteFile = fs.promises.writeFile.bind(fs.promises);
    vi.spyOn(fs.promises, "writeFile").mockImplementation(
      async (target, data, options) => {
        if (
          String(target).includes(path.join("runtime", "run-cleanup")) &&
          String(target).endsWith("plugin.json")
        ) {
          throw new Error("Simulated runtime metadata failure");
        }
        return originalWriteFile(target, data, options);
      },
    );

    await expect(
      service.prepareRuntimePlugins("run-cleanup", new Set()),
    ).rejects.toThrow("Simulated runtime metadata failure");
    await expect(
      fs.promises.lstat(
        path.join(appDataPath, "agent-plugins", "runtime", "run-cleanup"),
      ),
    ).rejects.toMatchObject({ code: "ENOENT" });
  });

  it.each([
    [
      "file bytes",
      async (skillDirectory: string) => {
        await writeSparseFile(
          path.join(skillDirectory, "large.bin"),
          1024 * 1024 + 1,
        );
      },
    ],
    [
      "file count",
      async (skillDirectory: string) => {
        await Promise.all(
          Array.from({ length: 256 }, (_, index) =>
            fs.promises.writeFile(
              path.join(skillDirectory, `file-${index}.txt`),
              "x",
            ),
          ),
        );
      },
    ],
    [
      "skill bytes",
      async (skillDirectory: string) => {
        await Promise.all(
          Array.from({ length: 8 }, (_, index) =>
            writeSparseFile(
              path.join(skillDirectory, `chunk-${index}.bin`),
              1024 * 1024,
            ),
          ),
        );
      },
    ],
  ])(
    "skips a skill that exceeds the snapshot %s limit",
    async (_label, addPayload) => {
      const appDataPath = path.join(root, "app-data");
      const pluginDirectory = path.join(root, "plugin");
      await writePlugin(pluginDirectory);
      const skillDirectory = await writeSkill(pluginDirectory, "summarize");
      const service = createService(appDataPath, [pluginDirectory]);
      await registerSelectedPlugin(service);
      await addPayload(skillDirectory);
      const skipped: string[] = [];

      const runtime = await service.prepareRuntimePlugins(
        `run-${_label.replace(" ", "-")}`,
        new Set(),
        (_pluginName, skillName) => skipped.push(skillName),
      );

      expect(runtime).toEqual([]);
      expect(skipped).toEqual(["summarize"]);
    },
  );

  it.each([
    [
      "files",
      async (skillDirectories: string[]) => {
        for (const skillDirectory of skillDirectories) {
          await Promise.all(
            Array.from({ length: 255 }, (_, index) =>
              fs.promises.writeFile(
                path.join(skillDirectory, `file-${index}.txt`),
                "x",
              ),
            ),
          );
        }
      },
    ],
    [
      "bytes",
      async (skillDirectories: string[]) => {
        await Promise.all(
          skillDirectories.flatMap((skillDirectory) =>
            Array.from({ length: 7 }, (_, index) =>
              writeSparseFile(
                path.join(skillDirectory, `chunk-${index}.bin`),
                1024 * 1024,
              ),
            ),
          ),
        );
      },
    ],
  ])("bounds the total %s copied for one plugin", async (label, addPayload) => {
    const appDataPath = path.join(root, "app-data");
    const pluginDirectory = path.join(root, "plugin");
    await writePlugin(pluginDirectory);
    const skillDirectories = await Promise.all(
      Array.from({ length: 5 }, (_, index) =>
        writeSkill(pluginDirectory, `skill-${index}`),
      ),
    );
    const service = createService(appDataPath, [pluginDirectory]);
    await registerSelectedPlugin(service);
    await addPayload(skillDirectories);
    const skipped: string[] = [];

    const runtime = await service.prepareRuntimePlugins(
      `run-plugin-${label}`,
      new Set(),
      (_pluginName, skillName) => skipped.push(skillName),
    );

    expect(runtime).toHaveLength(1);
    expect(await fs.promises.readdir(runtime[0].skillsPath)).toHaveLength(4);
    expect(skipped).toEqual(["skill-4"]);
  });

  it.each(["../outside", "000000000000000g", "short"])(
    "rejects malformed installation ID %s",
    async (invalidId) => {
      const service = createService(path.join(root, "app-data"));

      await expect(service.setEnabled(invalidId, false)).rejects.toThrow(
        "Invalid Agent Plugin installation ID",
      );
      await expect(service.unregister(invalidId)).rejects.toThrow(
        "Invalid Agent Plugin installation ID",
      );
    },
  );

  it("rejects removal of a missing installation", async () => {
    const service = createService(path.join(root, "app-data"));

    await expect(service.unregister("0000000000000000")).rejects.toThrow(
      "Agent Plugin installation not found",
    );
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
