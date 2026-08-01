import os from "node:os";
import path from "node:path";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mockReadFile = vi.hoisted(() => vi.fn());
const mockStat = vi.hoisted(() => vi.fn());
const mockRealpath = vi.hoisted(() => vi.fn());

vi.mock("node:fs", () => {
  const promises = {
    readFile: mockReadFile,
    stat: mockStat,
    realpath: mockRealpath,
    access: vi.fn(),
    writeFile: vi.fn(),
    unlink: vi.fn(),
    readdir: vi.fn(),
    mkdir: vi.fn(),
    mkdtemp: vi.fn(),
  };
  const constants = { W_OK: 2 };
  return { promises, constants, default: { promises, constants } };
});

import { OsService } from "./os";

function createService() {
  const dialog = {
    pickFile: vi.fn(),
    confirm: vi.fn(),
  };
  const urlLauncher = { launch: vi.fn().mockResolvedValue(undefined) };
  const appMeta = { version: "9.9.9" };
  const imageProcessor = { downscale: vi.fn() };
  const workspaceSettings = {
    getWorktreeLocation: vi.fn(() => "/tmp/worktrees"),
  };

  const storagePaths = {
    appDataPath: "/data",
    logsPath: "/logs",
    logFolderPath: "/logs",
  };

  const service = new OsService(
    dialog as never,
    urlLauncher as never,
    appMeta as never,
    imageProcessor as never,
    workspaceSettings as never,
    storagePaths as never,
  );

  return { service, dialog, urlLauncher, appMeta, workspaceSettings };
}

beforeEach(() => {
  vi.clearAllMocks();
  mockRealpath.mockImplementation(async (p: string) => p);
});

describe("OsService.showMessageBox", () => {
  it("maps options onto dialog.confirm and returns the chosen response", async () => {
    const { service, dialog } = createService();
    dialog.confirm.mockResolvedValue(1);

    const result = await service.showMessageBox({
      type: "warning",
      title: "Heads up",
      message: "Are you sure?",
      buttons: ["Cancel", "Proceed"],
      defaultId: 1,
      cancelId: 0,
    });

    expect(result).toEqual({ response: 1 });
    expect(dialog.confirm).toHaveBeenCalledWith(
      expect.objectContaining({
        severity: "warning",
        title: "Heads up",
        message: "Are you sure?",
        options: ["Cancel", "Proceed"],
        defaultIndex: 1,
        cancelIndex: 0,
      }),
    );
  });

  it("treats a 'none' type as no severity", async () => {
    const { service, dialog } = createService();
    dialog.confirm.mockResolvedValue(0);

    await service.showMessageBox({ type: "none", message: "hi" });

    expect(dialog.confirm).toHaveBeenCalledWith(
      expect.objectContaining({ severity: undefined }),
    );
  });

  it("falls back to a default title and an OK button", async () => {
    const { service, dialog } = createService();
    dialog.confirm.mockResolvedValue(0);

    await service.showMessageBox({ message: "" });

    expect(dialog.confirm).toHaveBeenCalledWith(
      expect.objectContaining({ title: "PostHog", options: ["OK"] }),
    );
  });
});

describe("OsService directory and file pickers", () => {
  it("returns the first picked path for selectDirectory", async () => {
    const { service, dialog } = createService();
    dialog.pickFile.mockResolvedValue(["/repo/one", "/repo/two"]);
    expect(await service.selectDirectory()).toBe("/repo/one");
  });

  it("returns null from selectDirectory when nothing is picked", async () => {
    const { service, dialog } = createService();
    dialog.pickFile.mockResolvedValue([]);
    expect(await service.selectDirectory()).toBeNull();
  });

  it("passes through the picked files for selectFiles", async () => {
    const { service, dialog } = createService();
    dialog.pickFile.mockResolvedValue(["/a.txt", "/b.txt"]);
    expect(await service.selectFiles()).toEqual(["/a.txt", "/b.txt"]);
  });

  it("classifies selected attachments by stat kind and drops unreadable ones", async () => {
    const { service, dialog } = createService();
    dialog.pickFile.mockResolvedValue(["/dir", "/file", "/gone"]);
    mockStat.mockImplementation(async (p: string) => {
      if (p === "/gone") throw new Error("ENOENT");
      return { isDirectory: () => p === "/dir" };
    });

    const result = await service.selectAttachments("both");

    expect(result).toEqual([
      { path: "/dir", kind: "directory" },
      { path: "/file", kind: "file" },
    ]);
    expect(dialog.pickFile).toHaveBeenCalledWith(
      expect.objectContaining({ filesAndDirectories: true, multiple: true }),
    );
  });
});

describe("OsService simple delegations", () => {
  it("returns the app version from app meta", () => {
    const { service } = createService();
    expect(service.getAppVersion()).toBe("9.9.9");
  });

  it("returns the worktree location from workspace settings", () => {
    const { service } = createService();
    expect(service.getWorktreeLocation()).toBe("/tmp/worktrees");
  });

  it("opens external URLs through the url launcher", async () => {
    const { service, urlLauncher } = createService();
    await service.openExternal("https://posthog.com");
    expect(urlLauncher.launch).toHaveBeenCalledWith("https://posthog.com");
  });

  it("opens the log folder as a file URL via the url launcher", async () => {
    const { service, urlLauncher } = createService();
    await service.showLogFolder();
    expect(urlLauncher.launch).toHaveBeenCalledWith(
      expect.stringMatching(/^file:\/\//),
    );
  });
});

describe("OsService.getUserAgentInstructions", () => {
  const home = os.homedir();
  const agentsPath = path.join(home, ".agents", "AGENTS.md");
  const codexPath = path.join(home, ".codex", "AGENTS.md");
  const claudePath = path.join(home, ".claude", "CLAUDE.md");

  function givenFiles(files: Record<string, string>) {
    mockReadFile.mockImplementation(async (filePath: string) => {
      if (filePath in files) return files[filePath];
      throw new Error("ENOENT");
    });
  }

  it.each([
    {
      label: "prefers an AGENTS.md over the user CLAUDE.md",
      files: {
        [codexPath]: "codex instructions",
        [claudePath]: "claude instructions",
      },
      winner: {
        path: codexPath,
        displayPath: "~/.codex/AGENTS.md",
        content: "codex instructions",
      },
    },
    {
      label: "prefers ~/.agents/AGENTS.md over ~/.codex/AGENTS.md",
      files: {
        [agentsPath]: "agents instructions",
        [codexPath]: "codex instructions",
      },
      winner: {
        path: agentsPath,
        displayPath: "~/.agents/AGENTS.md",
        content: "agents instructions",
      },
    },
    {
      label: "falls back to the user CLAUDE.md when no AGENTS.md exists",
      files: { [claudePath]: "claude instructions" },
      winner: {
        path: claudePath,
        displayPath: "~/.claude/CLAUDE.md",
        content: "claude instructions",
      },
    },
  ])("$label", async ({ files, winner }) => {
    const { service } = createService();
    givenFiles(files);

    expect(await service.getUserAgentInstructions()).toEqual({
      ...winner,
      truncated: false,
    });
  });

  it("skips whitespace-only files", async () => {
    const { service } = createService();
    givenFiles({ [agentsPath]: "  \n\t", [claudePath]: "real instructions" });

    const result = await service.getUserAgentInstructions();
    expect(result?.path).toBe(claudePath);
  });

  it("returns null when no candidate file exists", async () => {
    const { service } = createService();
    givenFiles({});

    expect(await service.getUserAgentInstructions()).toBeNull();
  });

  it("truncates oversized files and flags the truncation", async () => {
    const { service } = createService();
    givenFiles({ [claudePath]: "x".repeat(25_000) });

    const result = await service.getUserAgentInstructions();
    expect(result?.content).toHaveLength(20_000);
    expect(result?.truncated).toBe(true);
  });
});

describe("OsService.getUserAgentInstructions @-import expansion", () => {
  const home = os.homedir();
  const claudeDir = path.join(home, ".claude");
  const claudePath = path.join(claudeDir, "CLAUDE.md");
  const aPath = path.join(claudeDir, "a.md");
  const bPath = path.join(claudeDir, "b.md");
  const engineeringPath = path.join(claudeDir, "engineering.md");

  function givenFiles(files: Record<string, string>) {
    mockReadFile.mockImplementation(async (filePath: string) => {
      if (filePath in files) return files[filePath];
      throw new Error("ENOENT");
    });
  }

  it.each([
    {
      label: "leaves files without imports untouched",
      files: { [claudePath]: "just plain rules\nno imports here" },
      expected: "just plain rules\nno imports here",
    },
    {
      label: "inlines a single relative import",
      files: {
        [claudePath]: "top rules\n@./engineering.md",
        [engineeringPath]: "engineering rules",
      },
      expected: "top rules\nengineering rules",
    },
    {
      label: "recursively inlines nested imports",
      files: {
        [claudePath]: "@./a.md",
        [aPath]: "A\n@./b.md",
        [bPath]: "B",
      },
      expected: "A\nB",
    },
    {
      label: "leaves the reference literal on a cycle",
      files: {
        [claudePath]: "@./a.md",
        [aPath]: "A\n@./a.md",
      },
      expected: "A\n@./a.md",
    },
    {
      label: "leaves a missing import as its literal reference",
      files: { [claudePath]: "top\n@./missing.md" },
      expected: "top\n@./missing.md",
    },
    {
      label: "does not expand imports inside inline code spans",
      files: {
        [claudePath]: "mention `@./engineering.md` literally",
        [engineeringPath]: "engineering rules",
      },
      expected: "mention `@./engineering.md` literally",
    },
    {
      label: "does not expand imports inside fenced code blocks",
      files: {
        [claudePath]: "```\n@./engineering.md\n```",
        [engineeringPath]: "engineering rules",
      },
      expected: "```\n@./engineering.md\n```",
    },
    {
      label: "a shorter fence line does not close a longer fence",
      files: {
        [claudePath]: "````\n```\n@./engineering.md\n```\n````",
        [engineeringPath]: "engineering rules",
      },
      expected: "````\n```\n@./engineering.md\n```\n````",
    },
    {
      label: "a longer fence line closes a shorter fence",
      files: {
        [claudePath]: "```\n@./engineering.md\n````\n@./engineering.md",
        [engineeringPath]: "engineering rules",
      },
      expected: "```\n@./engineering.md\n````\nengineering rules",
    },
    {
      label: "a backtick fence line does not close a tilde fence",
      files: {
        [claudePath]: "~~~\n```\n@./engineering.md\n~~~",
        [engineeringPath]: "engineering rules",
      },
      expected: "~~~\n```\n@./engineering.md\n~~~",
    },
    {
      label: "a tilde fence line does not close a backtick fence",
      files: {
        [claudePath]: "```\n~~~\n@./engineering.md\n```",
        [engineeringPath]: "engineering rules",
      },
      expected: "```\n~~~\n@./engineering.md\n```",
    },
    {
      label: "expands after a normally closed fence",
      files: {
        [claudePath]: "```\n@./engineering.md\n```\n@./engineering.md",
        [engineeringPath]: "engineering rules",
      },
      expected: "```\n@./engineering.md\n```\nengineering rules",
    },
    {
      label: "a fence line with an info string is not a closer",
      files: {
        [claudePath]: "```\n@./engineering.md\n``` js\n@./engineering.md\n```",
        [engineeringPath]: "engineering rules",
      },
      expected: "```\n@./engineering.md\n``` js\n@./engineering.md\n```",
    },
    {
      label:
        "a backtick run with backticks in its info string is a span, not a fence",
      files: {
        [claudePath]: "```@x```\n@./engineering.md",
        [engineeringPath]: "engineering rules",
      },
      expected: "```@x```\nengineering rules",
    },
    {
      label: "keeps an indented code line after a blank line literal",
      files: {
        [claudePath]: "intro\n\n    @./engineering.md",
        [engineeringPath]: "engineering rules",
      },
      expected: "intro\n\n    @./engineering.md",
    },
    {
      label: "keeps a tab-indented code line after a blank line literal",
      files: {
        [claudePath]: "intro\n\n\t@./engineering.md",
        [engineeringPath]: "engineering rules",
      },
      expected: "intro\n\n\t@./engineering.md",
    },
    {
      label: "expands an indented list continuation without a preceding blank",
      files: {
        [claudePath]: "- see:\n    @./engineering.md",
        [engineeringPath]: "engineering rules",
      },
      expected: "- see:\n    engineering rules",
    },
    {
      label:
        "an indented code block survives internal blanks and ends on dedent",
      files: {
        [claudePath]:
          "intro\n\n    @./engineering.md\n\nafter @./engineering.md",
        [engineeringPath]: "engineering rules",
      },
      expected: "intro\n\n    @./engineering.md\n\nafter engineering rules",
    },
    {
      label: "a three-space indent is not an indented code block",
      files: {
        [claudePath]: "intro\n\n   @./engineering.md",
        [engineeringPath]: "engineering rules",
      },
      expected: "intro\n\n   engineering rules",
    },
    {
      label: "a four-space-indented fence line is indented code, not a fence",
      files: {
        [claudePath]: "intro\n\n    ````\n@./engineering.md",
        [engineeringPath]: "engineering rules",
      },
      expected: "intro\n\n    ````\nengineering rules",
    },
    {
      label: "does not expand imports inside double-backtick code spans",
      files: {
        [claudePath]: "see `` @./engineering.md `` then @./engineering.md",
        [engineeringPath]: "engineering rules",
      },
      expected: "see `` @./engineering.md `` then engineering rules",
    },
    {
      label: "a double-backtick span may contain a single backtick",
      files: {
        [claudePath]: "`` a`b `` @./engineering.md",
        [engineeringPath]: "engineering rules",
      },
      expected: "`` a`b `` engineering rules",
    },
    {
      label: "expands after an unmatched backtick run",
      files: {
        [claudePath]: "a lone ` backtick then @./engineering.md",
        [engineeringPath]: "engineering rules",
      },
      expected: "a lone ` backtick then engineering rules",
    },
    {
      label: "expands outside a span at the start of a line",
      files: {
        [claudePath]: "`@./engineering.md` and @./engineering.md",
        [engineeringPath]: "engineering rules",
      },
      expected: "`@./engineering.md` and engineering rules",
    },
    {
      label: "expands between two code spans",
      files: {
        [claudePath]: "`a` @./engineering.md `b`",
        [engineeringPath]: "engineering rules",
      },
      expected: "`a` engineering rules `b`",
    },
  ])("$label", async ({ files, expected }) => {
    const { service } = createService();
    givenFiles(files);

    const result = await service.getUserAgentInstructions();
    expect(result?.content).toBe(expected);
    expect(result?.truncated).toBe(false);
  });

  it("stops following imports past the max depth", async () => {
    const { service } = createService();
    const chain = path.join(claudeDir, "d5.md");
    givenFiles({
      [claudePath]: "@./d1.md",
      [path.join(claudeDir, "d1.md")]: "1\n@./d2.md",
      [path.join(claudeDir, "d2.md")]: "2\n@./d3.md",
      [path.join(claudeDir, "d3.md")]: "3\n@./d4.md",
      [path.join(claudeDir, "d4.md")]: "4\n@./d5.md",
      [chain]: "5",
    });

    const result = await service.getUserAgentInstructions();
    expect(result?.content).toBe("1\n2\n3\n4\n@./d5.md");
  });

  it("resolves relative imports against a symlinked file's real directory", async () => {
    const { service } = createService();
    const realDir = path.join(path.sep, "dotfiles", "claude");
    const realClaudePath = path.join(realDir, "CLAUDE.md");
    const realEngineeringPath = path.join(realDir, "engineering.md");

    mockRealpath.mockImplementation(async (p: string) =>
      p === claudePath ? realClaudePath : p,
    );
    givenFiles({
      [claudePath]: "root\n@./engineering.md",
      [realEngineeringPath]: "engineering rules from dotfiles",
    });

    const result = await service.getUserAgentInstructions();
    expect(result?.content).toBe("root\nengineering rules from dotfiles");
  });

  it("applies the length cap after expansion", async () => {
    const { service } = createService();
    givenFiles({
      [claudePath]: "@./big.md",
      [path.join(claudeDir, "big.md")]: "x".repeat(25_000),
    });

    const result = await service.getUserAgentInstructions();
    expect(result?.content).toHaveLength(20_000);
    expect(result?.truncated).toBe(true);
  });
});

describe("OsService.getClaudePermissions", () => {
  it("returns the allow and deny arrays from the settings file", async () => {
    const { service } = createService();
    mockReadFile.mockResolvedValue(
      JSON.stringify({ permissions: { allow: ["Read"], deny: ["Bash"] } }),
    );

    expect(await service.getClaudePermissions()).toEqual({
      allow: ["Read"],
      deny: ["Bash"],
    });
  });

  it("returns empty arrays when the settings file is missing", async () => {
    const { service } = createService();
    mockReadFile.mockRejectedValue(new Error("ENOENT"));

    expect(await service.getClaudePermissions()).toEqual({
      allow: [],
      deny: [],
    });
  });

  it("returns empty arrays when permissions are malformed", async () => {
    const { service } = createService();
    mockReadFile.mockResolvedValue(
      JSON.stringify({ permissions: { allow: "not-an-array" } }),
    );

    expect(await service.getClaudePermissions()).toEqual({
      allow: [],
      deny: [],
    });
  });
});
