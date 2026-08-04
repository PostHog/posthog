import { mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { LocalMcpServiceImpl } from "./local-mcp";

let home: string;
let originalHome: string | undefined;

async function writeClaudeJson(data: unknown) {
  await writeFile(path.join(home, ".claude.json"), JSON.stringify(data));
}

beforeEach(async () => {
  home = await mkdtemp(path.join(tmpdir(), "local-mcp-test-"));
  originalHome = process.env.HOME;
  process.env.HOME = home;
});

afterEach(async () => {
  process.env.HOME = originalHome;
  await rm(home, { recursive: true, force: true });
});

describe("LocalMcpServiceImpl.listServers", () => {
  it("returns empty when ~/.claude.json is missing or malformed", async () => {
    const service = new LocalMcpServiceImpl();
    expect(await service.listServers()).toEqual([]);

    await writeFile(path.join(home, ".claude.json"), "not json");
    expect(await service.listServers()).toEqual([]);
  });

  it("normalizes http, sse, and stdio servers with their scope", async () => {
    await writeClaudeJson({
      mcpServers: {
        grafana: {
          type: "http",
          url: "https://grafana.example.com/mcp",
          headers: { Authorization: "Bearer abc" },
        },
        legacy: { type: "sse", url: "https://sse.example.com/mcp" },
        playwright: {
          type: "stdio",
          command: "npx",
          args: ["@playwright/mcp@latest"],
          env: { SECRET: "do-not-leak" },
        },
      },
      projects: {
        "/repo": {
          mcpServers: {
            docs: { type: "http", url: "http://localhost:3001/mcp" },
          },
        },
      },
    });

    const servers = await new LocalMcpServiceImpl().listServers("/repo");

    expect(servers).toEqual([
      {
        name: "grafana",
        scope: "user",
        transport: {
          type: "http",
          url: "https://grafana.example.com/mcp",
          headers: { Authorization: "Bearer abc" },
        },
      },
      {
        name: "legacy",
        scope: "user",
        transport: { type: "sse", url: "https://sse.example.com/mcp" },
      },
      {
        name: "playwright",
        scope: "user",
        transport: {
          type: "stdio",
          command: "npx",
          args: ["@playwright/mcp@latest"],
        },
      },
      {
        name: "docs",
        scope: "project",
        transport: { type: "http", url: "http://localhost:3001/mcp" },
      },
    ]);
  });

  it("omits project-scoped servers when no cwd is given", async () => {
    await writeClaudeJson({
      mcpServers: { top: { type: "http", url: "https://a.example.com" } },
      projects: {
        "/repo": {
          mcpServers: {
            scoped: { type: "http", url: "https://b.example.com" },
          },
        },
      },
    });

    const servers = await new LocalMcpServiceImpl().listServers();
    expect(servers.map((s) => s.name)).toEqual(["top"]);
  });

  it.each([
    {
      name: "command without type is stdio",
      config: { command: "uvx", args: ["some-mcp"] },
      transport: { type: "stdio", command: "uvx", args: ["some-mcp"] },
    },
    {
      name: "bare url without type is read as http",
      config: { url: "https://bare.example.com/mcp" },
      transport: { type: "http", url: "https://bare.example.com/mcp" },
    },
    {
      name: "unrecognized shape is unknown",
      config: { type: "websocket", endpoint: "wss://x" },
      transport: { type: "unknown" },
    },
  ])("$name", async ({ config, transport }) => {
    await writeClaudeJson({ mcpServers: { server: config } });
    const servers = await new LocalMcpServiceImpl().listServers();
    expect(servers).toEqual([{ name: "server", scope: "user", transport }]);
  });
});
