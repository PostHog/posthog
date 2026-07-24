import {
  existsSync,
  mkdirSync,
  mkdtempSync,
  rmSync,
  symlinkSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";
import { removeLegacyNodeShimDirs } from "./legacy-node-shim";

const rmSyncSpy = vi.hoisted(() => vi.fn());

vi.mock("node:fs", async (importOriginal) => {
  const original = await importOriginal<typeof import("node:fs")>();
  rmSyncSpy.mockImplementation(original.rmSync);
  return { ...original, rmSync: rmSyncSpy };
});

describe("removeLegacyNodeShimDirs", () => {
  const roots: string[] = [];

  function makeRoot(): string {
    const root = mkdtempSync(join(tmpdir(), "legacy-shim-test-"));
    roots.push(root);
    return root;
  }

  afterEach(() => {
    while (roots.length > 0) {
      const root = roots.pop();
      if (root) rmSync(root, { recursive: true, force: true });
    }
  });

  it.each([
    ["agent-node-dev", "wrapper-script"],
    ["agent-node-prod", "symlink"],
  ] as const)("removes a leftover %s dir with a %s shim", (name, kind) => {
    const root = makeRoot();
    const dir = join(root, name);
    mkdirSync(dir, { recursive: true });
    const shim = join(dir, "node");
    if (kind === "symlink") {
      symlinkSync("/does/not/exist", shim);
    } else {
      writeFileSync(shim, "#!/bin/sh\n");
    }

    expect(removeLegacyNodeShimDirs(root)).toEqual({
      removed: [dir],
      failed: [],
    });
    expect(existsSync(dir)).toBe(false);
  });

  it("reports a failed removal and still cleans the other dir", () => {
    const root = makeRoot();
    const dev = join(root, "agent-node-dev");
    const prod = join(root, "agent-node-prod");
    mkdirSync(dev, { recursive: true });
    mkdirSync(prod, { recursive: true });
    rmSyncSpy.mockImplementationOnce(() => {
      throw new Error("EACCES");
    });

    expect(removeLegacyNodeShimDirs(root)).toEqual({
      removed: [prod],
      failed: [dev],
    });
    expect(existsSync(dev)).toBe(true);
    expect(existsSync(prod)).toBe(false);
  });

  it("removes a shim dir that is itself a symlink without touching its target", () => {
    const root = makeRoot();
    const target = makeRoot();
    const marker = join(target, "keep-me");
    writeFileSync(marker, "");
    const link = join(root, "agent-node-dev");
    symlinkSync(target, link);

    expect(removeLegacyNodeShimDirs(root)).toEqual({
      removed: [link],
      failed: [],
    });
    expect(existsSync(link)).toBe(false);
    expect(existsSync(marker)).toBe(true);
  });

  it("returns empty lists when nothing is left to clean", () => {
    expect(removeLegacyNodeShimDirs(makeRoot())).toEqual({
      removed: [],
      failed: [],
    });
  });
});
