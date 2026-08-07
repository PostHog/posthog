import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import {
  buildStdioEnvironment,
  expandPluginPlaceholders,
  resolveStdioServer,
} from "./stdio-runtime";

let root: string;

async function makePlugin(name: string): Promise<string> {
  const pluginRoot = path.join(root, name);
  await fs.promises.mkdir(path.join(pluginRoot, "bin"), { recursive: true });
  await fs.promises.mkdir(path.join(pluginRoot, "work"), { recursive: true });
  await fs.promises.writeFile(path.join(pluginRoot, "bin", "server"), "server");
  return pluginRoot;
}

describe("Agent Plugin stdio runtime", () => {
  beforeEach(async () => {
    root = await fs.promises.mkdtemp(
      path.join(os.tmpdir(), "agent-plugin-stdio-runtime-"),
    );
  });

  afterEach(async () => {
    await fs.promises.rm(root, { recursive: true, force: true });
  });

  it("expands only the two exact placeholders in one pass", () => {
    const pluginRoot = `/plugin/\${PLUGIN_DATA}`;
    const pluginData = "/data";

    expect(
      expandPluginPlaceholders(
        `\${PLUGIN_ROOT}:\${PLUGIN_DATA}:\${HOME}:\${PLUGIN_ROOTED}`,
        pluginRoot,
        pluginData,
      ),
    ).toBe(`/plugin/\${PLUGIN_DATA}:/data:\${HOME}:\${PLUGIN_ROOTED}`);
  });

  it("builds an allowlisted environment with configured values overlaid and roots set last", () => {
    const environment = buildStdioEnvironment(
      {
        HOME: "/home/example",
        PATH: "/usr/bin",
        POSTHOG_API_KEY: "must-not-leak",
      },
      {
        PATH: `\${PLUGIN_ROOT}/bin`,
        CONFIG: `\${PLUGIN_DATA}/config.json`,
        PLUGIN_ROOT: "/malicious",
      },
      "/plugin",
      "/plugin-data",
      "linux",
    );

    expect(environment).toMatchObject({
      HOME: "/home/example",
      PATH: "/plugin/bin",
      CONFIG: "/plugin-data/config.json",
      PLUGIN_ROOT: "/plugin",
      PLUGIN_DATA: "/plugin-data",
    });
    expect(environment).not.toHaveProperty("POSTHOG_API_KEY");
  });

  it.each([
    ["default", undefined, "plugin"],
    ["plugin relative", "./work", "work"],
    ["plugin root", `\${PLUGIN_ROOT}/work`, "work"],
    ["plugin data", `\${PLUGIN_DATA}/cache/nested`, "data"],
  ])("resolves the %s working directory", async (_label, cwd, expected) => {
    const pluginRoot = await makePlugin(
      `plugin-${_label.replaceAll(" ", "-")}`,
    );
    const pluginData = path.join(root, "data", _label.replaceAll(" ", "-"));

    const resolved = await resolveStdioServer(
      pluginRoot,
      pluginData,
      {
        name: "server",
        type: "stdio",
        command: "./bin/server",
        args: [`\${PLUGIN_ROOT}`, `\${PLUGIN_DATA}`],
        env: { CONFIG: `\${PLUGIN_DATA}/config` },
        ...(cwd === undefined ? {} : { cwd }),
      },
      { HOME: "/home/example", PATH: "/usr/bin" },
    );

    expect(resolved.command).toBe(
      path.join(resolved.pluginRoot, "bin", "server"),
    );
    expect(resolved.args).toEqual([resolved.pluginRoot, resolved.pluginData]);
    expect(resolved.env.CONFIG).toBe(`${resolved.pluginData}/config`);
    expect(resolved.cwd).toBe(
      expected === "plugin"
        ? resolved.pluginRoot
        : expected === "data"
          ? path.join(resolved.pluginData, "cache", "nested")
          : path.join(resolved.pluginRoot, expected),
    );
  });

  it("keeps plugin data stable and isolated by installation path", async () => {
    const pluginRoot = await makePlugin("plugin");
    const firstData = path.join(root, "data", "installation-a");
    const secondData = path.join(root, "data", "installation-b");

    const first = await resolveStdioServer(pluginRoot, firstData, {
      name: "server",
      type: "stdio",
      command: "node",
    });
    await fs.promises.writeFile(
      path.join(first.pluginData, "state.json"),
      "{}",
    );
    const restarted = await resolveStdioServer(pluginRoot, firstData, {
      name: "server",
      type: "stdio",
      command: "node",
    });
    const isolated = await resolveStdioServer(pluginRoot, secondData, {
      name: "server",
      type: "stdio",
      command: "node",
    });

    expect(restarted.pluginData).toBe(first.pluginData);
    expect(
      await fs.promises.readFile(
        path.join(restarted.pluginData, "state.json"),
        "utf8",
      ),
    ).toBe("{}");
    expect(isolated.pluginData).not.toBe(first.pluginData);
  });

  it("rejects plugin data that escapes app-managed storage through a symlink", async () => {
    const pluginRoot = await makePlugin("plugin");
    const dataParent = path.join(root, "data");
    const outside = path.join(root, "outside-data");
    await fs.promises.mkdir(dataParent);
    await fs.promises.mkdir(outside);
    await fs.promises.symlink(outside, path.join(dataParent, "installation"));

    await expect(
      resolveStdioServer(pluginRoot, path.join(dataParent, "installation"), {
        name: "server",
        type: "stdio",
        command: "node",
      }),
    ).rejects.toThrow("escapes app-managed storage");
  });

  it("rejects a working directory that escapes through a symlink", async () => {
    const pluginRoot = await makePlugin("plugin");
    const outside = path.join(root, "outside");
    await fs.promises.mkdir(outside);
    await fs.promises.symlink(outside, path.join(pluginRoot, "escape"));

    await expect(
      resolveStdioServer(pluginRoot, path.join(root, "data"), {
        name: "server",
        type: "stdio",
        command: "node",
        cwd: "./escape",
      }),
    ).rejects.toThrow("escapes its allowed root");
  });
});
