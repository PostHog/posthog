import { existsSync, readFileSync, statSync } from "node:fs";
import {
  chmod,
  mkdir,
  mkdtemp,
  readlink,
  rm,
  writeFile,
} from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const testHome = vi.hoisted(() => ({ dir: "" }));

vi.mock("node:os", async (importOriginal) => {
  const actual = await importOriginal<typeof import("node:os")>();
  const homedir = () => testHome.dir;
  return { ...actual, homedir, default: { ...actual, homedir } };
});

import {
  cleanupCodexHome,
  getCodexHomeDir,
  getCodexSubscriptionHomeDir,
  prepareCodexHome,
  stripMcpServers,
  writeBackSubscriptionLogin,
} from "./codex-home";

const noopLog = { debug() {}, info() {}, warn() {}, error() {} };

const taskRunId = "run-1";

let root: string;
let appDataPath: string;
let bundledSkillsDir: string;
let userSkillsDir: string;

async function createSkill(dir: string, name: string, body = `# ${name}`) {
  await mkdir(path.join(dir, name), { recursive: true });
  await writeFile(path.join(dir, name, "SKILL.md"), body);
}

beforeEach(async () => {
  root = await mkdtemp(path.join(tmpdir(), "codex-home-test-"));
  testHome.dir = path.join(root, "home");
  appDataPath = path.join(root, "appdata");
  bundledSkillsDir = path.join(root, "bundled", "skills");
  userSkillsDir = path.join(testHome.dir, ".claude", "skills");
  await mkdir(appDataPath, { recursive: true });
  await mkdir(bundledSkillsDir, { recursive: true });
});

afterEach(async () => {
  await rm(root, { recursive: true, force: true });
  vi.restoreAllMocks();
});

describe("prepareCodexHome", () => {
  it("links bundled and user Claude skills into <appData>/codex-home/skills", async () => {
    await createSkill(bundledSkillsDir, "query-data");
    await createSkill(userSkillsDir, "my-skill");

    const codexHome = await prepareCodexHome({
      appDataPath,
      taskRunId,
      bundledSkillsDir,
      log: noopLog,
    });

    expect(codexHome).toBe(path.join(appDataPath, "codex-home", taskRunId));
    const skillsDir = path.join(codexHome, "skills");
    expect(existsSync(path.join(skillsDir, "query-data", "SKILL.md"))).toBe(
      true,
    );
    expect(existsSync(path.join(skillsDir, "my-skill", "SKILL.md"))).toBe(true);
  });

  it("lets the bundled catalog win on a name collision", async () => {
    await createSkill(bundledSkillsDir, "dup", "bundled body");
    await createSkill(userSkillsDir, "dup", "user body");

    const codexHome = await prepareCodexHome({
      appDataPath,
      taskRunId,
      bundledSkillsDir,
      log: noopLog,
    });

    const linked = await readlink(path.join(codexHome, "skills", "dup"));
    expect(readFileSync(path.join(linked, "SKILL.md"), "utf-8")).toBe(
      "bundled body",
    );
  });

  it("copies the user's ~/.codex/config.toml without its mcp_servers tables", async () => {
    const codexConfigDir = path.join(testHome.dir, ".codex");
    await mkdir(codexConfigDir, { recursive: true });
    const configPath = path.join(codexConfigDir, "config.toml");
    await writeFile(
      configPath,
      [
        'model = "gpt-5-codex"',
        "[mcp_servers.mem0]",
        'url = "https://mcp.example.com/mcp/"',
        '[projects."/repo"]',
        'trust_level = "trusted"',
        "",
      ].join("\n"),
    );

    const codexHome = await prepareCodexHome({
      appDataPath,
      taskRunId,
      bundledSkillsDir,
      log: noopLog,
    });

    const privateConfig = path.join(codexHome, "config.toml");
    expect(readFileSync(privateConfig, "utf-8")).toBe(
      'model = "gpt-5-codex"\n[projects."/repo"]\ntrust_level = "trusted"\n',
    );
  });

  it.skipIf(process.platform === "win32")(
    "writes the copied config so only its owner can read it",
    async () => {
      const codexConfigDir = path.join(testHome.dir, ".codex");
      await mkdir(codexConfigDir, { recursive: true });
      await writeFile(
        path.join(codexConfigDir, "config.toml"),
        'model = "gpt-5-codex"\n',
      );

      const codexHome = await prepareCodexHome({
        appDataPath,
        taskRunId,
        bundledSkillsDir,
        log: noopLog,
      });

      const mode = statSync(path.join(codexHome, "config.toml")).mode & 0o777;
      expect(mode).toBe(0o600);
    },
  );

  it("rebuilds the skills dir, dropping stale links", async () => {
    await createSkill(bundledSkillsDir, "first");
    await prepareCodexHome({
      appDataPath,
      taskRunId,
      bundledSkillsDir,
      log: noopLog,
    });

    await rm(path.join(bundledSkillsDir, "first"), { recursive: true });
    await createSkill(bundledSkillsDir, "second");
    const codexHome = await prepareCodexHome({
      appDataPath,
      taskRunId,
      bundledSkillsDir,
      log: noopLog,
    });

    const skillsDir = path.join(codexHome, "skills");
    expect(existsSync(path.join(skillsDir, "first"))).toBe(false);
    expect(existsSync(path.join(skillsDir, "second"))).toBe(true);
  });

  it("gives each task run an isolated dir, so concurrent runs never share", async () => {
    await createSkill(bundledSkillsDir, "query-data");

    const [homeA, homeB] = await Promise.all([
      prepareCodexHome({
        appDataPath,
        taskRunId: "run-a",
        bundledSkillsDir,
        log: noopLog,
      }),
      prepareCodexHome({
        appDataPath,
        taskRunId: "run-b",
        bundledSkillsDir,
        log: noopLog,
      }),
    ]);

    expect(homeA).not.toBe(homeB);
    expect(existsSync(path.join(homeA, "skills", "query-data"))).toBe(true);
    expect(existsSync(path.join(homeB, "skills", "query-data"))).toBe(true);
  });

  it("cleanupCodexHome removes the run's dir and is a no-op when absent", async () => {
    await createSkill(bundledSkillsDir, "query-data");
    const codexHome = await prepareCodexHome({
      appDataPath,
      taskRunId,
      bundledSkillsDir,
      log: noopLog,
    });
    expect(existsSync(codexHome)).toBe(true);

    await cleanupCodexHome(appDataPath, taskRunId);
    expect(existsSync(codexHome)).toBe(false);
    expect(existsSync(getCodexHomeDir(appDataPath, taskRunId))).toBe(false);

    // Second call on a now-absent dir must not throw.
    await expect(
      cleanupCodexHome(appDataPath, taskRunId),
    ).resolves.toBeUndefined();
  });

  it("seeds the stored login into the run's own home for subscription sessions", async () => {
    const subscriptionHome = getCodexSubscriptionHomeDir(appDataPath);
    await mkdir(subscriptionHome, { recursive: true });
    await writeFile(path.join(subscriptionHome, "auth.json"), '{"token":1}');

    const codexHome = await prepareCodexHome({
      appDataPath,
      taskRunId,
      subscription: true,
      bundledSkillsDir,
      log: noopLog,
    });

    expect(codexHome).toBe(path.join(appDataPath, "codex-home", taskRunId));
    expect(readFileSync(path.join(codexHome, "auth.json"), "utf-8")).toBe(
      '{"token":1}',
    );

    await cleanupCodexHome(appDataPath, taskRunId);
    expect(existsSync(codexHome)).toBe(false);
    expect(existsSync(path.join(subscriptionHome, "auth.json"))).toBe(true);
  });

  it.skipIf(process.platform === "win32")(
    "writes the seeded login so only its owner can read it",
    async () => {
      const subscriptionHome = getCodexSubscriptionHomeDir(appDataPath);
      await mkdir(subscriptionHome, { recursive: true });
      await writeFile(path.join(subscriptionHome, "auth.json"), "{}");

      const codexHome = await prepareCodexHome({
        appDataPath,
        taskRunId,
        subscription: true,
        bundledSkillsDir,
        log: noopLog,
      });

      const mode = statSync(path.join(codexHome, "auth.json")).mode & 0o777;
      expect(mode).toBe(0o600);
    },
  );

  it.skipIf(process.platform === "win32")(
    "re-seeding a retried run keeps the login owner-only",
    async () => {
      const subscriptionHome = getCodexSubscriptionHomeDir(appDataPath);
      await mkdir(subscriptionHome, { recursive: true });
      await writeFile(path.join(subscriptionHome, "auth.json"), "{}");

      const first = await prepareCodexHome({
        appDataPath,
        taskRunId,
        subscription: true,
        bundledSkillsDir,
        log: noopLog,
      });
      // Codex rewrites auth.json during a run; do not count on its mode.
      await chmod(path.join(first, "auth.json"), 0o644);

      const second = await prepareCodexHome({
        appDataPath,
        taskRunId,
        subscription: true,
        bundledSkillsDir,
        log: noopLog,
      });
      expect(statSync(path.join(second, "auth.json")).mode & 0o777).toBe(0o600);
    },
  );

  it("throws for a subscription session without a stored login", async () => {
    await expect(
      prepareCodexHome({
        appDataPath,
        taskRunId,
        subscription: true,
        bundledSkillsDir,
        log: noopLog,
      }),
    ).rejects.toThrow("Subscription login not found");
  });

  it("gives concurrent subscription runs isolated homes seeded from the same login", async () => {
    const subscriptionHome = getCodexSubscriptionHomeDir(appDataPath);
    await mkdir(subscriptionHome, { recursive: true });
    await writeFile(path.join(subscriptionHome, "auth.json"), '{"token":1}');
    await createSkill(bundledSkillsDir, "query-data");

    const [homeA, homeB] = await Promise.all([
      prepareCodexHome({
        appDataPath,
        taskRunId: "run-a",
        subscription: true,
        bundledSkillsDir,
        log: noopLog,
      }),
      prepareCodexHome({
        appDataPath,
        taskRunId: "run-b",
        subscription: true,
        bundledSkillsDir,
        log: noopLog,
      }),
    ]);

    expect(homeA).not.toBe(homeB);
    for (const home of [homeA, homeB]) {
      expect(readFileSync(path.join(home, "auth.json"), "utf-8")).toBe(
        '{"token":1}',
      );
      expect(existsSync(path.join(home, "skills", "query-data"))).toBe(true);
    }
  });

  it("writeBackSubscriptionLogin carries refreshed tokens into the stored login", async () => {
    const subscriptionHome = getCodexSubscriptionHomeDir(appDataPath);
    await mkdir(subscriptionHome, { recursive: true });
    const storedLogin = path.join(subscriptionHome, "auth.json");
    await writeFile(storedLogin, '{"token":1}');

    const codexHome = await prepareCodexHome({
      appDataPath,
      taskRunId,
      subscription: true,
      bundledSkillsDir,
      log: noopLog,
    });
    // Codex rotates OAuth tokens during a run and saves them in its home.
    await writeFile(path.join(codexHome, "auth.json"), '{"token":2}');

    await writeBackSubscriptionLogin({ appDataPath, taskRunId, log: noopLog });
    expect(readFileSync(storedLogin, "utf-8")).toBe('{"token":2}');

    await cleanupCodexHome(appDataPath, taskRunId);
    expect(readFileSync(storedLogin, "utf-8")).toBe('{"token":2}');
  });

  it.skipIf(process.platform === "win32")(
    "writeBackSubscriptionLogin leaves the rewritten store owner-only",
    async () => {
      const subscriptionHome = getCodexSubscriptionHomeDir(appDataPath);
      await mkdir(subscriptionHome, { recursive: true });
      const storedLogin = path.join(subscriptionHome, "auth.json");
      // Older builds wrote the store without a mode (0644).
      await writeFile(storedLogin, '{"token":1}');

      const codexHome = await prepareCodexHome({
        appDataPath,
        taskRunId,
        subscription: true,
        bundledSkillsDir,
        log: noopLog,
      });
      await writeFile(path.join(codexHome, "auth.json"), '{"token":2}');

      await writeBackSubscriptionLogin({
        appDataPath,
        taskRunId,
        log: noopLog,
      });

      expect(statSync(storedLogin).mode & 0o777).toBe(0o600);
    },
  );

  it("writeBackSubscriptionLogin never overwrites a login that changed since seeding", async () => {
    const subscriptionHome = getCodexSubscriptionHomeDir(appDataPath);
    await mkdir(subscriptionHome, { recursive: true });
    const storedLogin = path.join(subscriptionHome, "auth.json");
    await writeFile(storedLogin, '{"token":1}');

    const codexHome = await prepareCodexHome({
      appDataPath,
      taskRunId,
      subscription: true,
      bundledSkillsDir,
      log: noopLog,
    });
    await writeFile(path.join(codexHome, "auth.json"), '{"token":2}');

    // The user signed out and connected another account mid-run.
    await writeFile(storedLogin, '{"token":"other-account"}');

    await writeBackSubscriptionLogin({ appDataPath, taskRunId, log: noopLog });
    expect(readFileSync(storedLogin, "utf-8")).toBe(
      '{"token":"other-account"}',
    );
  });

  it("writeBackSubscriptionLogin lets only the first of two concurrent runs write back", async () => {
    const subscriptionHome = getCodexSubscriptionHomeDir(appDataPath);
    await mkdir(subscriptionHome, { recursive: true });
    const storedLogin = path.join(subscriptionHome, "auth.json");
    await writeFile(storedLogin, '{"token":1}');

    const seed = (id: string) =>
      prepareCodexHome({
        appDataPath,
        taskRunId: id,
        subscription: true,
        bundledSkillsDir,
        log: noopLog,
      });
    const homeA = await seed("run-a");
    const homeB = await seed("run-b");
    await writeFile(path.join(homeA, "auth.json"), '{"token":"a2"}');
    await writeFile(path.join(homeB, "auth.json"), '{"token":"b2"}');

    await writeBackSubscriptionLogin({
      appDataPath,
      taskRunId: "run-a",
      log: noopLog,
    });
    expect(readFileSync(storedLogin, "utf-8")).toBe('{"token":"a2"}');

    await writeBackSubscriptionLogin({
      appDataPath,
      taskRunId: "run-b",
      log: noopLog,
    });
    expect(readFileSync(storedLogin, "utf-8")).toBe('{"token":"a2"}');
  });

  it("writeBackSubscriptionLogin skips runs seeded before seed hashes existed", async () => {
    const subscriptionHome = getCodexSubscriptionHomeDir(appDataPath);
    const runHome = path.join(appDataPath, "codex-home", taskRunId);
    await mkdir(subscriptionHome, { recursive: true });
    await mkdir(runHome, { recursive: true });
    const storedLogin = path.join(subscriptionHome, "auth.json");
    await writeFile(storedLogin, '{"token":1}');
    await writeFile(path.join(runHome, "auth.json"), '{"token":2}');

    await writeBackSubscriptionLogin({ appDataPath, taskRunId, log: noopLog });
    expect(readFileSync(storedLogin, "utf-8")).toBe('{"token":1}');
  });

  it("writeBackSubscriptionLogin does not resurrect a login after sign-out", async () => {
    const subscriptionHome = getCodexSubscriptionHomeDir(appDataPath);
    await mkdir(subscriptionHome, { recursive: true });
    await writeFile(path.join(subscriptionHome, "auth.json"), '{"token":1}');

    const codexHome = await prepareCodexHome({
      appDataPath,
      taskRunId,
      subscription: true,
      bundledSkillsDir,
      log: noopLog,
    });
    await writeFile(path.join(codexHome, "auth.json"), '{"token":2}');

    // The user signed out mid-run.
    await rm(path.join(subscriptionHome, "auth.json"));

    await writeBackSubscriptionLogin({ appDataPath, taskRunId, log: noopLog });
    expect(existsSync(path.join(subscriptionHome, "auth.json"))).toBe(false);
  });

  it("writeBackSubscriptionLogin is a no-op for runs without a seeded login", async () => {
    await prepareCodexHome({
      appDataPath,
      taskRunId,
      bundledSkillsDir,
      log: noopLog,
    });

    await expect(
      writeBackSubscriptionLogin({ appDataPath, taskRunId, log: noopLog }),
    ).resolves.toBeUndefined();
    expect(
      existsSync(
        path.join(getCodexSubscriptionHomeDir(appDataPath), "auth.json"),
      ),
    ).toBe(false);
  });

  it("rejects an unsafe taskRunId instead of escaping the codex-home dir", async () => {
    const outside = path.join(appDataPath, "keep-me");
    await createSkill(outside, "precious");

    for (const badId of ["", ".", "..", "../../escape", "nested/evil"]) {
      expect(() => getCodexHomeDir(appDataPath, badId)).toThrow();
      await expect(
        prepareCodexHome({
          appDataPath,
          taskRunId: badId,
          bundledSkillsDir,
          log: noopLog,
        }),
      ).rejects.toThrow();
      await expect(cleanupCodexHome(appDataPath, badId)).rejects.toThrow();
    }

    expect(existsSync(path.join(outside, "precious", "SKILL.md"))).toBe(true);
  });
});

describe("stripMcpServers", () => {
  it.each([
    {
      name: "drops a server table and its nested sub-tables",
      toml: [
        'model = "gpt-5"',
        "[mcp_servers.node_repl]",
        'command = "node"',
        "[mcp_servers.node_repl.env]",
        'FOO = "bar"',
        "[features]",
        "memories = true",
      ],
      expected: ['model = "gpt-5"', "[features]", "memories = true"],
    },
    {
      name: "drops the parent table with dotted keys",
      toml: [
        "[mcp_servers]",
        'mem0.url = "https://x/mcp"',
        "[tui]",
        "theme = 1",
      ],
      expected: ["[tui]", "theme = 1"],
    },
    {
      name: "drops top-level inline and dotted keys",
      toml: [
        'mcp_servers = { mem0 = { url = "https://x/mcp" } }',
        'mcp_servers.other.command = "x"',
        'model = "gpt-5"',
      ],
      expected: ['model = "gpt-5"'],
    },
    {
      name: "drops quoted and array-of-table headers",
      toml: [
        '[mcp_servers."my.server"]',
        'command = "x"',
        "[[mcp_servers.list]]",
        'command = "y"',
        '[projects."/repo"]',
        'trust_level = "trusted"',
      ],
      expected: ['[projects."/repo"]', 'trust_level = "trusted"'],
    },
    {
      name: "keeps keys that merely start with the prefix",
      toml: ['mcp_servers_note = "keep"', "[mcp_servers_extra]", 'k = "v"'],
      expected: ['mcp_servers_note = "keep"', "[mcp_servers_extra]", 'k = "v"'],
    },
    {
      name: "keeps a dotted key inside another table",
      toml: ["[tui]", 'mcp_servers.hint = "keep"'],
      expected: ["[tui]", 'mcp_servers.hint = "keep"'],
    },
    {
      name: "returns a config without mcp_servers unchanged",
      toml: ['model = "gpt-5"', "[tui]", "theme = 1"],
      expected: ['model = "gpt-5"', "[tui]", "theme = 1"],
    },
    {
      name: "keeps a multiline string whose content looks like a header",
      toml: [
        'notes = """',
        "[mcp_servers.example]",
        "how to add one",
        '"""',
        'model = "gpt-5"',
      ],
      expected: [
        'notes = """',
        "[mcp_servers.example]",
        "how to add one",
        '"""',
        'model = "gpt-5"',
      ],
    },
    {
      name: "keeps dropping a server table across a wrapped value",
      toml: [
        "[mcp_servers.docs]",
        "args = [",
        '  ["--flag"],',
        "]",
        'instructions = """',
        "[tui] is not a header here",
        '"""',
        "[tui]",
        "theme = 1",
      ],
      expected: ["[tui]", "theme = 1"],
    },
    {
      name: "drops a top-level key together with its wrapped value",
      toml: [
        "mcp_servers.docs.args = [",
        '  "--flag",',
        "]",
        'mcp_servers.docs.instructions = """',
        "read me",
        '"""',
        'model = "gpt-5"',
      ],
      expected: ['model = "gpt-5"'],
    },
    {
      name: "keeps a bracket inside a quoted value from opening a table",
      toml: ["[mcp_servers.docs]", 'command = "["', "[tui]", "theme = 1"],
      expected: ["[tui]", "theme = 1"],
    },
    {
      name: "keeps a quoted triple quote from opening a multiline string",
      toml: [
        "marker = \"'''\"",
        "[mcp_servers.docs]",
        'command = "x"',
        "[tui]",
      ],
      expected: ["marker = \"'''\"", "[tui]"],
    },
  ])("$name", ({ toml, expected }) => {
    expect(stripMcpServers(toml.join("\n"))).toBe(expected.join("\n"));
  });
});
