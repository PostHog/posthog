import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  AgentPluginsService,
  agentPluginRuntimeMcpName,
} from "./agent-plugins";
import type {
  AgentPluginHttpProxy,
  AgentPluginHttpProxyRegistration,
} from "./http-proxy";
import { loadAgentPlugin } from "./loader";
import {
  AGENT_PLUGINS_MANIFEST_SCHEMA,
  AGENT_PLUGINS_MCP_SCHEMA,
} from "./schemas";
import type { AgentPluginStdioBridge } from "./stdio-bridge";

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

async function writeMcp(
  pluginDirectory: string,
  mcpServers: Record<string, unknown>,
  extra: Record<string, unknown> = {},
): Promise<void> {
  await fs.promises.writeFile(
    path.join(pluginDirectory, "mcp.json"),
    JSON.stringify({
      $schema: AGENT_PLUGINS_MCP_SCHEMA,
      mcpServers,
      ...extra,
    }),
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

function createHttpProxy(): AgentPluginHttpProxy {
  return {
    register: vi.fn(async ({ id }: { id: string }) => `http://127.0.0.1/${id}`),
    unregisterRun: vi.fn(),
    unregisterInstallation: vi.fn(),
  };
}

function deferred(): { promise: Promise<void>; resolve: () => void } {
  let resolve = (): void => {};
  const promise = new Promise<void>((complete) => {
    resolve = complete;
  });
  return { promise, resolve };
}

function createDeferredHttpProxy(): {
  proxy: AgentPluginHttpProxy;
  active: Map<string, AgentPluginHttpProxyRegistration>;
  registrationStarted: Promise<void>;
  releaseRegistration: () => void;
} {
  const active = new Map<string, AgentPluginHttpProxyRegistration>();
  const started = deferred();
  const release = deferred();
  let registrationCount = 0;
  const proxy: AgentPluginHttpProxy = {
    register: vi.fn(async (registration) => {
      registrationCount += 1;
      if (registrationCount === 1) {
        started.resolve();
        await release.promise;
      }
      active.set(registration.id, registration);
      return `http://127.0.0.1/${registration.id}`;
    }),
    unregisterRun: vi.fn((runId) => {
      for (const [id, registration] of active) {
        if (registration.runId === runId) active.delete(id);
      }
    }),
    unregisterInstallation: vi.fn((installationId) => {
      for (const [id, registration] of active) {
        if (registration.installationId === installationId) active.delete(id);
      }
    }),
  };
  return {
    proxy,
    active,
    registrationStarted: started.promise,
    releaseRegistration: release.resolve,
  };
}

function createStdioBridge(): AgentPluginStdioBridge {
  return {
    register: vi.fn(async ({ id }: { id: string }) => `http://127.0.0.1/${id}`),
    unregisterRun: vi.fn(async () => undefined),
    unregisterInstallation: vi.fn(async () => undefined),
  };
}

function createService(
  appDataPath: string,
  selectedPaths: string[] = [],
  httpProxy: AgentPluginHttpProxy = createHttpProxy(),
  stdioBridge: AgentPluginStdioBridge = createStdioBridge(),
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
    httpProxy,
    stdioBridge,
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

  it("leaves installation state and managed data intact for a parent ID", async () => {
    const appDataPath = path.join(root, "app-data");
    const pluginDirectory = path.join(root, "plugin");
    await writePlugin(pluginDirectory);
    const service = createService(appDataPath, [pluginDirectory]);
    const installation = await registerSelectedPlugin(service);
    const dataDirectory = path.join(
      appDataPath,
      "agent-plugins",
      "data",
      installation.id,
    );
    await fs.promises.mkdir(dataDirectory, { recursive: true });
    const sentinelPath = path.join(dataDirectory, "sentinel.json");
    await fs.promises.writeFile(sentinelPath, "{}", "utf8");

    await expect(service.unregister("..")).rejects.toThrow(
      "Invalid Agent Plugin installation ID",
    );

    expect((await service.list()).map((plugin) => plugin.id)).toContain(
      installation.id,
    );
    await expect(fs.promises.readFile(sentinelPath, "utf8")).resolves.toBe(
      "{}",
    );
    await expect(
      fs.promises.stat(path.join(appDataPath, "agent-plugins")),
    ).resolves.toBeDefined();
  });

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

  it("rejects an oversized mcp.json before parsing it", async () => {
    const pluginDirectory = path.join(root, "plugin");
    await writePlugin(pluginDirectory);
    await writeSkill(pluginDirectory, "summarize");
    await writeSparseFile(
      path.join(pluginDirectory, "mcp.json"),
      1024 * 1024 + 1,
    );

    const preview = await loadAgentPlugin(pluginDirectory);

    expect(preview.valid).toBe(true);
    expect(preview.skills.map((skill) => skill.name)).toEqual(["summarize"]);
    expect(preview.mcpServers).toEqual([]);
    expect(preview.diagnostics).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ code: "invalid_mcp_config" }),
      ]),
    );
  });

  it("isolates a top-level MCP failure from valid skills", async () => {
    const pluginDirectory = path.join(root, "plugin");
    await writePlugin(pluginDirectory);
    await writeSkill(pluginDirectory, "summarize");
    await writeMcp(
      pluginDirectory,
      {
        analytics: {
          type: "streamable-http",
          url: "https://mcp.example.com/mcp",
        },
      },
      { unknown: true },
    );

    const preview = await loadAgentPlugin(pluginDirectory);

    expect(preview.valid).toBe(true);
    expect(preview.skills.map((skill) => skill.name)).toEqual(["summarize"]);
    expect(preview.mcpServers).toEqual([]);
    expect(preview.diagnostics).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ code: "invalid_mcp_config" }),
      ]),
    );
  });

  it("isolates invalid and unsupported MCP entries from valid siblings", async () => {
    const pluginDirectory = path.join(root, "plugin");
    await writePlugin(pluginDirectory);
    await writeMcp(pluginDirectory, {
      valid: {
        type: "streamable-http",
        url: "https://mcp.example.com/mcp",
      },
      invalid: {
        type: "streamable-http",
        url: "http://mcp.example.com/mcp",
      },
      local: { type: "stdio", command: "node", args: ["server.js"] },
      legacy: { type: "sse", url: "https://mcp.example.com/sse" },
    });

    const preview = await loadAgentPlugin(pluginDirectory);

    expect(preview.mcpServers.map((server) => server.name)).toEqual([
      "local",
      "valid",
    ]);
    expect(preview.diagnostics.map((item) => item.code)).toEqual(
      expect.arrayContaining([
        "invalid_mcp_server",
        "unsupported_mcp_transport",
      ]),
    );
  });

  it.each([
    ["HTTPS", "https://mcp.example.com/mcp", true],
    ["localhost HTTP", "http://localhost:3000/mcp", true],
    ["IPv4 loopback HTTP", "http://127.1.2.3:3000/mcp", true],
    ["IPv6 loopback HTTP", "http://[::1]:3000/mcp", true],
    ["non-loopback HTTP", "http://mcp.example.com/mcp", false],
    ["relative URL", "./mcp", false],
    ["userinfo", "https://user:password@mcp.example.com/mcp", false],
    ["fragment", "https://mcp.example.com/mcp#tools", false],
  ])("validates %s MCP URLs", async (_label, url, valid) => {
    const pluginDirectory = path.join(root, _label.replaceAll(" ", "-"));
    await writePlugin(pluginDirectory);
    await writeMcp(pluginDirectory, {
      server: { type: "streamable-http", url },
    });

    const preview = await loadAgentPlugin(pluginDirectory);

    expect(preview.mcpServers).toHaveLength(valid ? 1 : 0);
  });

  it("does not expose or persist HTTP header values", async () => {
    const pluginDirectory = path.join(root, "plugin");
    const appDataPath = path.join(root, "app-data");
    await writePlugin(pluginDirectory);
    await writeMcp(pluginDirectory, {
      analytics: {
        type: "streamable-http",
        url: "https://mcp.example.com/mcp",
        headers: { Authorization: "secret-value" },
      },
    });
    const service = createService(appDataPath, [pluginDirectory]);

    const preview = await service.selectDirectory();
    expect(preview?.mcpServers).toEqual([
      {
        name: "analytics",
        type: "streamable-http",
        supported: true,
        approval: "not-required",
      },
    ]);
    const installation = await service.register(preview?.selectionToken ?? "");
    expect(installation.mcpServers).toEqual(preview?.mcpServers);
    const state = await fs.promises.readFile(
      path.join(appDataPath, "agent-plugins", "installations.json"),
      "utf8",
    );
    expect(state).not.toContain("secret-value");
    expect(state).not.toContain("Authorization");
  });

  it("rejects plugin-relative stdio command and cwd symlink escapes", async () => {
    const pluginDirectory = path.join(root, "plugin");
    const outsideDirectory = path.join(root, "outside");
    await writePlugin(pluginDirectory);
    await fs.promises.mkdir(outsideDirectory);
    await fs.promises.writeFile(path.join(outsideDirectory, "server"), "bin");
    await fs.promises.mkdir(path.join(outsideDirectory, "cwd"));
    await fs.promises.symlink(
      path.join(outsideDirectory, "server"),
      path.join(pluginDirectory, "server"),
    );
    await fs.promises.symlink(
      path.join(outsideDirectory, "cwd"),
      path.join(pluginDirectory, "cwd"),
    );
    await writeMcp(pluginDirectory, {
      escapedCommand: { type: "stdio", command: "./server" },
      escapedCwd: { type: "stdio", command: "node", cwd: "./cwd" },
    });

    const preview = await loadAgentPlugin(pluginDirectory);

    expect(
      preview.diagnostics.filter((item) => item.code === "invalid_mcp_server"),
    ).toHaveLength(2);
    expect(
      preview.diagnostics.filter(
        (item) => item.code === "unsupported_mcp_transport",
      ),
    ).toHaveLength(0);
  });

  it("prepares deterministic MCP names and revokes disabled installations", async () => {
    const pluginDirectory = path.join(root, "plugin");
    const appDataPath = path.join(root, "app-data");
    await writePlugin(pluginDirectory);
    await writeMcp(pluginDirectory, {
      analytics: {
        type: "streamable-http",
        url: "https://mcp.example.com/mcp",
        headers: { "X-Plugin": "example" },
      },
    });
    const httpProxy = createHttpProxy();
    const service = createService(appDataPath, [pluginDirectory], httpProxy);
    const installation = await registerSelectedPlugin(service);
    const expectedName = agentPluginRuntimeMcpName(
      installation.id,
      installation.manifest.name,
      "analytics",
    );

    const runtime = await service.prepareRuntimeMcpServers(
      "task-1",
      "run-1",
      new Set(),
    );
    expect(runtime).toEqual([
      expect.objectContaining({ name: expectedName, type: "http" }),
    ]);
    expect(httpProxy.register).toHaveBeenCalledWith(
      expect.objectContaining({
        runId: "run-1",
        installationId: installation.id,
        url: "https://mcp.example.com/mcp",
        headers: { "X-Plugin": "example" },
      }),
    );

    await service.setEnabled(installation.id, false);
    expect(httpProxy.unregisterInstallation).toHaveBeenCalledWith(
      installation.id,
    );
    expect(
      await service.prepareRuntimeMcpServers("task-1", "run-2", new Set()),
    ).toEqual([]);
  });

  it("revokes HTTP targets when an installation is removed", async () => {
    const pluginDirectory = path.join(root, "plugin");
    const httpProxy = createHttpProxy();
    await writePlugin(pluginDirectory);
    const service = createService(
      path.join(root, "app-data"),
      [pluginDirectory],
      httpProxy,
    );
    const installation = await registerSelectedPlugin(service);

    await service.unregister(installation.id);

    expect(httpProxy.unregisterInstallation).toHaveBeenCalledWith(
      installation.id,
    );
  });

  it("serializes disable behind an in-flight MCP activation", async () => {
    const pluginDirectory = path.join(root, "plugin-disable-race");
    await writePlugin(pluginDirectory);
    await writeMcp(pluginDirectory, {
      analytics: {
        type: "streamable-http",
        url: "https://mcp.example.com/mcp",
      },
    });
    const deferredProxy = createDeferredHttpProxy();
    const service = createService(
      path.join(root, "app-data-disable-race"),
      [pluginDirectory],
      deferredProxy.proxy,
    );
    const installation = await registerSelectedPlugin(service);

    const activation = service.prepareRuntimeMcpServers(
      "task-1",
      "run-1",
      new Set(),
    );
    await deferredProxy.registrationStarted;
    const disable = service.setEnabled(installation.id, false);
    expect(deferredProxy.proxy.unregisterInstallation).not.toHaveBeenCalled();

    deferredProxy.releaseRegistration();
    await activation;
    await disable;

    expect(deferredProxy.active.size).toBe(0);
    expect(deferredProxy.proxy.unregisterInstallation).toHaveBeenCalledWith(
      installation.id,
    );
    await expect(
      service.prepareRuntimeMcpServers("task-1", "run-2", new Set()),
    ).resolves.toEqual([]);
    expect(deferredProxy.proxy.register).toHaveBeenCalledTimes(1);
  });

  it("serializes removal behind an in-flight MCP activation", async () => {
    const pluginDirectory = path.join(root, "plugin-remove-race");
    await writePlugin(pluginDirectory);
    await writeMcp(pluginDirectory, {
      analytics: {
        type: "streamable-http",
        url: "https://mcp.example.com/mcp",
      },
    });
    const deferredProxy = createDeferredHttpProxy();
    const service = createService(
      path.join(root, "app-data-remove-race"),
      [pluginDirectory],
      deferredProxy.proxy,
    );
    const installation = await registerSelectedPlugin(service);

    const activation = service.prepareRuntimeMcpServers(
      "task-1",
      "run-1",
      new Set(),
    );
    await deferredProxy.registrationStarted;
    const removal = service.unregister(installation.id);
    expect(deferredProxy.proxy.unregisterInstallation).not.toHaveBeenCalled();

    deferredProxy.releaseRegistration();
    await activation;
    await removal;

    expect(deferredProxy.active.size).toBe(0);
    expect(deferredProxy.proxy.unregisterInstallation).toHaveBeenCalledWith(
      installation.id,
    );
    await expect(service.list()).resolves.toEqual([]);
  });

  it("serializes concurrent MCP activations without leaking targets", async () => {
    const pluginDirectory = path.join(root, "plugin-concurrent-race");
    await writePlugin(pluginDirectory);
    await writeMcp(pluginDirectory, {
      analytics: {
        type: "streamable-http",
        url: "https://mcp.example.com/mcp",
      },
    });
    const deferredProxy = createDeferredHttpProxy();
    const service = createService(
      path.join(root, "app-data-concurrent-race"),
      [pluginDirectory],
      deferredProxy.proxy,
    );
    await registerSelectedPlugin(service);

    const first = service.prepareRuntimeMcpServers(
      "task-1",
      "run-1",
      new Set(),
    );
    await deferredProxy.registrationStarted;
    const second = service.prepareRuntimeMcpServers(
      "task-1",
      "run-1",
      new Set(),
    );
    expect(deferredProxy.proxy.register).toHaveBeenCalledTimes(1);

    deferredProxy.releaseRegistration();
    await Promise.all([first, second]);

    expect(deferredProxy.proxy.register).toHaveBeenCalledTimes(2);
    expect(deferredProxy.active.size).toBe(1);
  });

  it("requires fresh approval when stdio definitions change", async () => {
    const pluginDirectory = path.join(root, "plugin-consent");
    const appDataPath = path.join(root, "app-data-consent");
    await writePlugin(pluginDirectory);
    await writeMcp(pluginDirectory, {
      local: {
        type: "stdio",
        command: "node",
        args: ["one"],
        env: { PRIVATE_VALUE: "not-for-renderer" },
        cwd: "${PLUGIN_ROOT}",
      },
    });
    const stdioBridge = createStdioBridge();
    const service = createService(
      appDataPath,
      [pluginDirectory],
      createHttpProxy(),
      stdioBridge,
    );
    const installation = await registerSelectedPlugin(service);

    expect(installation.stdioApprovalRequired).toBe(false);
    expect(installation.mcpServers[0]).toMatchObject({
      command: "node",
      args: ["one"],
      envNames: ["PRIVATE_VALUE"],
      approval: "approved",
    });
    expect(installation.mcpServers[0]).not.toHaveProperty("digest");
    expect(JSON.stringify(installation)).not.toContain("not-for-renderer");
    const persistedState = await fs.promises.readFile(
      path.join(appDataPath, "agent-plugins", "installations.json"),
      "utf8",
    );
    expect(persistedState).not.toContain("not-for-renderer");
    expect(JSON.parse(persistedState).installations[0]).not.toHaveProperty(
      "mcpServers",
    );

    await writeMcp(pluginDirectory, {
      local: { type: "stdio", command: "node", args: ["two"] },
    });
    const changed = (await service.list())[0];
    expect(changed.stdioApprovalRequired).toBe(true);
    expect(changed.mcpServers[0]?.approval).toBe("required");
    expect(
      await service.prepareRuntimeMcpServers("task-1", "run-1", new Set()),
    ).toEqual([]);
    expect(stdioBridge.register).not.toHaveBeenCalled();

    await service.setEnabled(installation.id, false);
    await expect(service.setEnabled(installation.id, true)).rejects.toThrow(
      "Review and approve",
    );
    const approved = await service.approveStdio(installation.id);
    expect(approved.enabled).toBe(true);
    expect(approved.stdioApprovalRequired).toBe(false);
    await service.prepareRuntimeMcpServers("task-1", "run-2", new Set());
    const bridgeRegistration = vi.mocked(stdioBridge.register).mock
      .calls[0]?.[0];
    expect(bridgeRegistration).toBeDefined();

    await writeMcp(pluginDirectory, {
      local: { type: "stdio", command: "node", args: ["three"] },
    });
    await expect(bridgeRegistration?.prepare()).rejects.toThrow(
      "changed after it was approved",
    );

    await writeMcp(pluginDirectory, {});
    const removed = (await service.list())[0];
    expect(removed.stdioApprovalRequired).toBe(false);
    expect(removed.mcpServers).toEqual([]);
  });

  it("keeps active HTTP servers registered when approving stdio changes", async () => {
    const pluginDirectory = path.join(root, "mixed-plugin");
    const appDataPath = path.join(root, "mixed-app-data");
    await writePlugin(pluginDirectory);
    await writeMcp(pluginDirectory, {
      remote: {
        type: "streamable-http",
        url: "https://mcp.example.com/mcp",
      },
      local: { type: "stdio", command: "node", args: ["one"] },
    });
    const httpProxy = createHttpProxy();
    const stdioBridge = createStdioBridge();
    const service = createService(
      appDataPath,
      [pluginDirectory],
      httpProxy,
      stdioBridge,
    );
    const installation = await registerSelectedPlugin(service);
    await service.prepareRuntimeMcpServers("task-1", "run-1", new Set());

    await writeMcp(pluginDirectory, {
      remote: {
        type: "streamable-http",
        url: "https://mcp.example.com/mcp",
      },
      local: { type: "stdio", command: "node", args: ["two"] },
    });
    await service.approveStdio(installation.id);

    expect(httpProxy.unregisterInstallation).not.toHaveBeenCalled();
    expect(stdioBridge.unregisterInstallation).toHaveBeenCalledWith(
      installation.id,
    );
  });
});
