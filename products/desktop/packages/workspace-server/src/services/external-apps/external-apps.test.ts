import { describe, expect, it } from "vitest";
import { type OpenCommand, resolveOpenCommand } from "./external-apps";

const MALICIOUS_PATH = "/repo/$(touch /tmp/pwned)`whoami`; rm -rf x.txt";

const app = (id: string, path: string) => ({ id, path });

describe("resolveOpenCommand", () => {
  it.each<{
    name: string;
    platform: NodeJS.Platform;
    app: { id: string; path: string };
    isFile: boolean;
    expected: OpenCommand;
  }>([
    {
      name: "darwin finder reveal",
      platform: "darwin",
      app: app("finder", "/System/Library/CoreServices/Finder.app"),
      isFile: true,
      expected: { file: "open", args: ["-R", MALICIOUS_PATH] },
    },
    {
      name: "darwin gitkraken",
      platform: "darwin",
      app: app("gitkraken", "/Applications/GitKraken.app"),
      isFile: false,
      expected: {
        file: "open",
        args: [
          "-na",
          "/Applications/GitKraken.app",
          "--args",
          "-p",
          MALICIOUS_PATH,
        ],
      },
    },
    {
      name: "darwin default editor",
      platform: "darwin",
      app: app("vscode", "/Applications/Code.app"),
      isFile: false,
      expected: {
        file: "open",
        args: ["-a", "/Applications/Code.app", MALICIOUS_PATH],
      },
    },
    {
      name: "win32 explorer select",
      platform: "win32",
      app: app("explorer", "explorer.exe"),
      isFile: true,
      expected: { file: "explorer.exe", args: [`/select,${MALICIOUS_PATH}`] },
    },
    {
      name: "win32 default editor",
      platform: "win32",
      app: app("vscode", "C:/Code/Code.exe"),
      isFile: false,
      expected: { file: "C:/Code/Code.exe", args: [MALICIOUS_PATH] },
    },
  ])(
    "passes the crafted path as a single argv element: $name",
    ({ platform, app: a, isFile, expected }) => {
      const result = resolveOpenCommand(platform, a, MALICIOUS_PATH, isFile);

      expect(result).toEqual(expected);
      expect(result?.args).toContain(
        expected.args.find((arg) => arg.includes(MALICIOUS_PATH)),
      );
    },
  );

  it("returns null for an unsupported platform", () => {
    expect(
      resolveOpenCommand("linux", app("vscode", "/usr/bin/code"), "/x", false),
    ).toBeNull();
  });
});
