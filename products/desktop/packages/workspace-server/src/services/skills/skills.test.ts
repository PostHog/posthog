import { existsSync } from "node:fs";
import { mkdir, mkdtemp, rm, symlink, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { FoldersService } from "../folders/folders";
import type { PosthogPluginService } from "../posthog-plugin/posthog-plugin";
import { WatcherService } from "../watcher/service";
import { SkillsService } from "./skills";

const codexHome = vi.hoisted(() => ({ dir: "" }));
const userSkillsHome = vi.hoisted(() => ({ dir: "" }));

vi.mock("../posthog-plugin/codex-mirror", async (importOriginal) => {
  const actual =
    await importOriginal<typeof import("../posthog-plugin/codex-mirror")>();
  return { ...actual, getCodexSkillsDir: () => codexHome.dir };
});

vi.mock("./skill-discovery", async (importOriginal) => {
  const actual = await importOriginal<typeof import("./skill-discovery")>();
  return { ...actual, getUserSkillsDir: () => userSkillsHome.dir };
});

let root: string;
let pluginPath: string;
let folderPath: string;
let repoSkillsDir: string;

function makeService(): SkillsService {
  const plugin = {
    getPluginPath: () => pluginPath,
  } as unknown as PosthogPluginService;
  const folders = {
    getFolders: async () => [{ path: folderPath, name: "my-repo" }],
  } as unknown as FoldersService;
  return new SkillsService(plugin, folders, new WatcherService());
}

async function createSkill(
  skillsDir: string,
  name: string,
  content = `---\nname: ${name}\ndescription: about ${name}\n---\nbody`,
): Promise<string> {
  const skillPath = path.join(skillsDir, name);
  await mkdir(skillPath, { recursive: true });
  await writeFile(path.join(skillPath, "SKILL.md"), content);
  return skillPath;
}

beforeEach(async () => {
  root = await mkdtemp(path.join(tmpdir(), "skills-service-test-"));
  pluginPath = path.join(root, "plugin");
  folderPath = path.join(root, "repo");
  repoSkillsDir = path.join(folderPath, ".claude", "skills");
  codexHome.dir = path.join(root, "codex-skills");
  userSkillsHome.dir = path.join(root, "user-skills");
  await mkdir(path.join(pluginPath, "skills"), { recursive: true });
  await mkdir(repoSkillsDir, { recursive: true });
});

afterEach(async () => {
  await rm(root, { recursive: true, force: true });
});

describe("listSkills", () => {
  it("marks repo skills editable and bundled skills read-only", async () => {
    await createSkill(repoSkillsDir, "repo-skill");
    await createSkill(path.join(pluginPath, "skills"), "bundled-skill");

    const skills = await makeService().listSkills();

    const repoSkill = skills.find((s) => s.name === "repo-skill");
    const bundledSkill = skills.find((s) => s.name === "bundled-skill");
    expect(repoSkill?.editable).toBe(true);
    expect(bundledSkill?.editable).toBe(false);
  });
});

describe("getSkillContents", () => {
  it("lists every file in the skill directory with relative paths", async () => {
    const skillPath = await createSkill(repoSkillsDir, "alpha");
    await mkdir(path.join(skillPath, "references"), { recursive: true });
    await writeFile(path.join(skillPath, "references", "guide.md"), "guide");
    await mkdir(path.join(skillPath, "scripts"), { recursive: true });
    await writeFile(path.join(skillPath, "scripts", "run.sh"), "echo hi");

    const contents = await makeService().getSkillContents(skillPath);

    expect(contents.files.map((f) => f.path)).toEqual([
      "SKILL.md",
      "references/guide.md",
      "scripts/run.sh",
    ]);
    for (const file of contents.files) {
      expect(file.size).toBeGreaterThan(0);
    }
  });

  it("rejects directories outside the discovery roots", async () => {
    const rogue = path.join(root, "rogue-skill");
    await mkdir(rogue, { recursive: true });
    await writeFile(path.join(rogue, "SKILL.md"), "rogue");

    await expect(makeService().getSkillContents(rogue)).rejects.toThrow(
      "not a known skill directory",
    );
  });

  it("rejects path traversal in the skill path", async () => {
    await createSkill(repoSkillsDir, "alpha");

    await expect(
      makeService().getSkillContents(
        path.join(repoSkillsDir, "alpha", "..", "..", "..", ".."),
      ),
    ).rejects.toThrow("not a known skill directory");
  });
});

describe("readSkillFile", () => {
  it("reads a nested file inside the skill directory", async () => {
    const skillPath = await createSkill(repoSkillsDir, "alpha");
    await mkdir(path.join(skillPath, "references"), { recursive: true });
    await writeFile(path.join(skillPath, "references", "guide.md"), "guide!");

    const content = await makeService().readSkillFile(
      skillPath,
      "references/guide.md",
    );

    expect(content).toBe("guide!");
  });

  it("rejects ../ traversal out of the skill directory", async () => {
    const skillPath = await createSkill(repoSkillsDir, "alpha");
    await createSkill(repoSkillsDir, "beta", "secret");

    await expect(
      makeService().readSkillFile(skillPath, "../beta/SKILL.md"),
    ).rejects.toThrow("path outside skill directory");
  });

  it("rejects absolute file paths", async () => {
    const skillPath = await createSkill(repoSkillsDir, "alpha");

    await expect(
      makeService().readSkillFile(skillPath, "/etc/passwd"),
    ).rejects.toThrow("path outside skill directory");
  });

  it("rejects an empty relative path", async () => {
    const skillPath = await createSkill(repoSkillsDir, "alpha");

    await expect(makeService().readSkillFile(skillPath, "")).rejects.toThrow(
      "path outside skill directory",
    );
  });

  it("returns null for missing files", async () => {
    const skillPath = await createSkill(repoSkillsDir, "alpha");

    expect(await makeService().readSkillFile(skillPath, "nope.md")).toBeNull();
  });

  it("returns null for symlinks escaping the skill directory", async () => {
    const skillPath = await createSkill(repoSkillsDir, "alpha");
    const secret = path.join(root, "secret.txt");
    await writeFile(secret, "top secret");
    await symlink(secret, path.join(skillPath, "leak.md"));

    expect(await makeService().readSkillFile(skillPath, "leak.md")).toBeNull();
  });

  it("returns null for files reached through a symlinked directory", async () => {
    const skillPath = await createSkill(repoSkillsDir, "alpha");
    const outside = path.join(root, "outside");
    await mkdir(outside, { recursive: true });
    await writeFile(path.join(outside, "secret.txt"), "top secret");
    await symlink(outside, path.join(skillPath, "evil"));

    expect(
      await makeService().readSkillFile(skillPath, "evil/secret.txt"),
    ).toBeNull();
  });

  it("reads symlinks that stay inside the skill directory", async () => {
    const skillPath = await createSkill(repoSkillsDir, "alpha");
    await writeFile(path.join(skillPath, "real.md"), "real content");
    await symlink(
      path.join(skillPath, "real.md"),
      path.join(skillPath, "alias.md"),
    );

    expect(await makeService().readSkillFile(skillPath, "alias.md")).toBe(
      "real content",
    );
  });
});

describe("codex skills", () => {
  it("lists codex skills, hiding bundled-synced and mirrored copies", async () => {
    await mkdir(codexHome.dir, { recursive: true });
    await createSkill(codexHome.dir, "codex-only");
    // Copy synced there by the official bundled pipeline:
    await createSkill(path.join(pluginPath, "skills"), "bundled-skill");
    await createSkill(codexHome.dir, "bundled-skill");
    // Copy mirrored out from the user's skills:
    await createSkill(codexHome.dir, "mirrored-skill");
    await writeFile(
      path.join(codexHome.dir, ".posthog-mirror.json"),
      JSON.stringify({ version: 1, mirrored: ["mirrored-skill"] }),
    );

    const skills = await makeService().listSkills();
    const codexSkills = skills.filter((s) => s.source === "codex");

    expect(codexSkills.map((s) => s.name)).toEqual(["codex-only"]);
    expect(codexSkills[0]?.editable).toBe(false);
  });

  it("hides a codex skill already imported into the user skills dir", async () => {
    await mkdir(codexHome.dir, { recursive: true });
    await createSkill(userSkillsHome.dir, "shared-skill");
    await createSkill(codexHome.dir, "shared-skill");
    await createSkill(codexHome.dir, "codex-only");

    const skills = await makeService().listSkills();
    const codexSkills = skills.filter((s) => s.source === "codex");

    expect(codexSkills.map((s) => s.name)).toEqual(["codex-only"]);
  });

  it("imports a codex skill into the user skills dir", async () => {
    await mkdir(codexHome.dir, { recursive: true });
    await createSkill(codexHome.dir, "codex-only");
    const service = makeService();

    const target = path.join(userSkillsHome.dir, "codex-only");
    const result = await service.importCodexSkill(
      path.join(codexHome.dir, "codex-only"),
    );

    expect(result.path).toBe(target);
    const content = await service.readSkillFile(target, "SKILL.md");
    expect(content).toContain("codex-only");
    // The original Codex skill is left untouched — we copy, never mirror back.
    expect(existsSync(path.join(codexHome.dir, "codex-only", "SKILL.md"))).toBe(
      true,
    );
  });

  it("rejects importing paths outside the codex skills dir", async () => {
    await createSkill(repoSkillsDir, "alpha");

    await expect(
      makeService().importCodexSkill(path.join(repoSkillsDir, "alpha")),
    ).rejects.toThrow("not a Codex skill directory");
  });
});

describe("exportSkill", () => {
  it("splits frontmatter from the body and collects text companion files", async () => {
    const skillPath = await createSkill(
      repoSkillsDir,
      "alpha",
      "---\nname: alpha\ndescription: About alpha\n---\n\n# Alpha body",
    );
    await mkdir(path.join(skillPath, "references"), { recursive: true });
    await writeFile(path.join(skillPath, "references", "guide.md"), "guide");
    await writeFile(
      path.join(skillPath, "logo.bin"),
      Buffer.from([0x89, 0x00, 0x4e, 0x47]),
    );

    const exported = await makeService().exportSkill(skillPath);

    expect(exported).toEqual({
      name: "alpha",
      description: "About alpha",
      body: "# Alpha body",
      files: [{ path: "references/guide.md", content: "guide" }],
      skipped: ["logo.bin"],
    });
  });

  it("refuses to export non-writable skills", async () => {
    await createSkill(path.join(pluginPath, "skills"), "bundled-skill");

    await expect(
      makeService().exportSkill(
        path.join(pluginPath, "skills", "bundled-skill"),
      ),
    ).rejects.toThrow("Access denied");
  });
});

describe("installTeamSkill", () => {
  const input = {
    name: "team-skill",
    description: "From the team",
    body: "# Team body",
    files: [{ path: "references/guide.md", content: "guide" }],
  };

  it("requires overwrite for an existing skill, then replaces it", async () => {
    const name = "team-skill";
    const target = path.join(userSkillsHome.dir, name);
    const service = makeService();

    const first = await service.installTeamSkill({ ...input, name });
    expect(first.path).toBe(target);

    await expect(service.installTeamSkill({ ...input, name })).rejects.toThrow(
      "already exists",
    );

    await service.installTeamSkill({ ...input, name, overwrite: true });
    const manifest = await service.readSkillFile(target, "SKILL.md");
    expect(manifest).toContain("From the team");
    expect(manifest).toContain("# Team body");
    const guide = await service.readSkillFile(target, "references/guide.md");
    expect(guide).toBe("guide");
  });

  it("rejects invalid names and unsafe file paths", async () => {
    const service = makeService();

    await expect(
      service.installTeamSkill({ ...input, name: "../escape" }),
    ).rejects.toThrow("Skill names must be");

    const name = "team-skill";
    const target = path.join(userSkillsHome.dir, name);
    await expect(
      service.installTeamSkill({
        ...input,
        name,
        files: [{ path: "../evil.md", content: "bad" }],
      }),
    ).rejects.toThrow("path outside skill directory");
    expect(existsSync(target)).toBe(false);
  });

  it("keeps the existing skill when an overwrite payload is invalid", async () => {
    const name = "team-skill";
    const target = path.join(userSkillsHome.dir, name);
    const service = makeService();
    await service.installTeamSkill({ ...input, name });

    await expect(
      service.installTeamSkill({
        ...input,
        name,
        overwrite: true,
        files: [{ path: "../evil.md", content: "bad" }],
      }),
    ).rejects.toThrow("path outside skill directory");

    const manifest = await service.readSkillFile(target, "SKILL.md");
    expect(manifest).toContain("# Team body");
  });
});

describe("watchSkillDirs", () => {
  it(
    "emits a debounced change event when a watched dir changes",
    { timeout: 15_000 },
    async () => {
      const service = makeService();
      const controller = new AbortController();
      const generator = service.watchSkillDirs(
        [repoSkillsDir],
        controller.signal,
      );

      const firstEvent = generator.next();
      // Give the native watcher a moment to attach before mutating the dir.
      await new Promise((r) => setTimeout(r, 500));
      await createSkill(repoSkillsDir, "watched-skill");

      const result = await Promise.race([
        firstEvent,
        new Promise<never>((_, reject) =>
          setTimeout(
            () => reject(new Error("timed out waiting for change event")),
            10_000,
          ),
        ),
      ]);
      expect(result).toEqual({ value: { changed: true }, done: false });

      controller.abort();
      await generator.return(undefined);
    },
  );

  it("finishes immediately with no directories", async () => {
    const generator = makeService().watchSkillDirs([]);
    expect(await generator.next()).toEqual({ value: undefined, done: true });
  });

  it(
    "picks up a skills dir created after the watch starts",
    { timeout: 15_000 },
    async () => {
      const service = makeService();
      const controller = new AbortController();
      const lateDir = path.join(root, "late-repo", ".claude", "skills");
      const generator = service.watchSkillDirs([lateDir], controller.signal);

      const firstEvent = generator.next();
      await new Promise((r) => setTimeout(r, 100));
      await mkdir(lateDir, { recursive: true });

      const result = await Promise.race([
        firstEvent,
        new Promise<never>((_, reject) =>
          setTimeout(
            () => reject(new Error("timed out waiting for change event")),
            10_000,
          ),
        ),
      ]);
      expect(result).toEqual({ value: { changed: true }, done: false });

      controller.abort();
      await generator.return(undefined);
    },
  );
});

describe("createSkill", () => {
  it("scaffolds a directory with a parseable SKILL.md", async () => {
    const service = makeService();

    const { path: skillPath } = await service.createSkill({
      scope: "repo",
      repoPath: folderPath,
      name: "new-skill",
    });

    expect(skillPath).toBe(path.join(repoSkillsDir, "new-skill"));
    const skills = await service.listSkills();
    const created = skills.find((s) => s.path === skillPath);
    expect(created).toMatchObject({ name: "new-skill", editable: true });
  });

  it("rejects invalid names", async () => {
    await expect(
      makeService().createSkill({
        scope: "repo",
        repoPath: folderPath,
        name: "../escape",
      }),
    ).rejects.toThrow("Skill names must be");
  });

  it("rejects repo scope for folders that are not open", async () => {
    await expect(
      makeService().createSkill({
        scope: "repo",
        repoPath: path.join(root, "other-repo"),
        name: "new-skill",
      }),
    ).rejects.toThrow("not an open workspace folder");
  });

  it("rejects duplicate names", async () => {
    await createSkill(repoSkillsDir, "alpha");

    await expect(
      makeService().createSkill({
        scope: "repo",
        repoPath: folderPath,
        name: "alpha",
      }),
    ).rejects.toThrow("already exists");
  });
});

describe("write-path guard", () => {
  it("only bundles skills from discovery roots", async () => {
    const skillPath = await createSkill(repoSkillsDir, "alpha");
    const rogue = path.join(root, "rogue");
    await createSkill(root, "rogue");
    const service = makeService();

    const bundled = await service.bundleLocalSkill({
      name: "alpha",
      source: "repo",
      path: skillPath,
    });
    expect(bundled.fileName).toBe("alpha.zip");

    await expect(
      service.bundleLocalSkill({
        name: "rogue",
        source: "user",
        path: rogue,
      }),
    ).rejects.toThrow("not a known skill directory");
  });

  it("rejects a repo skill reached through a symlinked skills directory", async () => {
    // The leaf check alone misses this: a repo committing `.claude/skills`
    // itself as a symlink makes every skill under it resolve outside the repo.
    const outside = path.join(root, "outside-skills");
    await createSkill(outside, "escapee");
    await rm(repoSkillsDir, { recursive: true, force: true });
    await symlink(outside, repoSkillsDir, "dir");
    const service = makeService();

    await expect(
      service.bundleLocalSkill({
        name: "escapee",
        source: "repo",
        path: path.join(repoSkillsDir, "escapee"),
      }),
    ).rejects.toThrow("resolves outside its repository");
  });

  it("rejects a symlinked repo skill root", async () => {
    // A repository could commit `.claude/skills/foo` as a symlink to a
    // directory outside the repo; bundling must refuse to follow it rather
    // than upload the external target.
    const target = await createSkill(root, "linked");
    const linkPath = path.join(repoSkillsDir, "linked");
    await symlink(target, linkPath, "dir");
    const service = makeService();

    await expect(
      service.bundleLocalSkill({
        name: "linked",
        source: "repo",
        path: linkPath,
      }),
    ).rejects.toThrow("resolves outside its repository");
  });

  it("rejects a symlinked skill root outside repo roots", async () => {
    // Non-repo roots have no repository anchor, so the bundler's own
    // leaf-symlink check is the guard there.
    const target = await createSkill(root, "linked");
    await mkdir(userSkillsHome.dir, { recursive: true });
    const linkPath = path.join(userSkillsHome.dir, "linked");
    await symlink(target, linkPath, "dir");
    const service = makeService();

    await expect(
      service.bundleLocalSkill({
        name: "linked",
        source: "user",
        path: linkPath,
      }),
    ).rejects.toThrow("not a symlink");
  });

  it.each([
    ["bundled skill", () => path.join(pluginPath, "skills", "bundled-skill")],
    ["arbitrary directory", () => path.join(root, "rogue")],
    [
      "traversal out of a writable root",
      () => path.join(repoSkillsDir, "alpha", "..", ".."),
    ],
  ])("rejects mutations against a %s", async (_label, target) => {
    await createSkill(path.join(pluginPath, "skills"), "bundled-skill");
    await createSkill(repoSkillsDir, "alpha");
    const { mkdir: mk, writeFile: wf } = await import("node:fs/promises");
    await mk(path.join(root, "rogue"), { recursive: true });
    await wf(path.join(root, "rogue", "SKILL.md"), "rogue");
    const service = makeService();

    await expect(
      service.saveSkillFile(target(), "SKILL.md", "x"),
    ).rejects.toThrow("Access denied");
    await expect(service.deleteSkill(target())).rejects.toThrow(
      "Access denied",
    );
  });

  it("rejects file writes that escape the skill directory", async () => {
    const skillPath = await createSkill(repoSkillsDir, "alpha");

    await expect(
      makeService().saveSkillFile(skillPath, "../beta.md", "x"),
    ).rejects.toThrow("path outside skill directory");
  });
});

describe("skill mutations", () => {
  it("round-trips manifest edits through the frontmatter parser", async () => {
    const skillPath = await createSkill(repoSkillsDir, "alpha");
    const service = makeService();

    await service.saveSkillManifest(skillPath, {
      name: "alpha",
      description: "Use when: testing",
      body: "# Alpha\n\nBody text",
    });

    const skills = await service.listSkills();
    const updated = skills.find((s) => s.path === skillPath);
    expect(updated).toMatchObject({
      name: "alpha",
      description: "Use when: testing",
    });
    const content = await service.readSkillFile(skillPath, "SKILL.md");
    expect(content).toContain("# Alpha");
  });

  it("rejects manifest saves without a name", async () => {
    const skillPath = await createSkill(repoSkillsDir, "alpha");

    await expect(
      makeService().saveSkillManifest(skillPath, {
        name: "  ",
        description: "",
        body: "",
      }),
    ).rejects.toThrow("Skill name is required");
  });

  it("creates, renames, and deletes companion files", async () => {
    const skillPath = await createSkill(repoSkillsDir, "alpha");
    const service = makeService();

    await service.saveSkillFile(skillPath, "references/guide.md", "guide");
    await service.renameSkillFile(
      skillPath,
      "references/guide.md",
      "references/manual.md",
    );
    let contents = await service.getSkillContents(skillPath);
    expect(contents.files.map((f) => f.path)).toEqual([
      "SKILL.md",
      "references/manual.md",
    ]);

    await service.deleteSkillFile(skillPath, "references/manual.md");
    contents = await service.getSkillContents(skillPath);
    expect(contents.files.map((f) => f.path)).toEqual(["SKILL.md"]);
  });

  it("refuses to delete or rename SKILL.md", async () => {
    const skillPath = await createSkill(repoSkillsDir, "alpha");
    const service = makeService();

    await expect(
      service.deleteSkillFile(skillPath, "SKILL.md"),
    ).rejects.toThrow("SKILL.md cannot be deleted");
    await expect(
      service.deleteSkillFile(skillPath, "./SKILL.md"),
    ).rejects.toThrow("SKILL.md cannot be deleted");
    await expect(
      service.renameSkillFile(skillPath, "SKILL.md", "OTHER.md"),
    ).rejects.toThrow("SKILL.md cannot be renamed");
  });

  it("deletes a whole skill", async () => {
    const skillPath = await createSkill(repoSkillsDir, "alpha");
    const service = makeService();

    await service.deleteSkill(skillPath);

    const skills = await service.listSkills();
    expect(skills.find((s) => s.path === skillPath)).toBeUndefined();
  });
});

describe("resolveSkillBundleDependencies", () => {
  function ref(name: string, skillPath: string) {
    return { name, source: "repo" as const, path: skillPath };
  }

  function withDeps(name: string, deps: string[]): string {
    return `---\nname: ${name}\ndescription: about ${name}\ndependencies:\n${deps
      .map((dep) => `  - ${dep}`)
      .join("\n")}\n---\nbody`;
  }

  it("expands prose references (/name and [[name]]) into dependencies", async () => {
    const primary = await createSkill(
      repoSkillsDir,
      "prose-parent",
      `---\nname: prose-parent\ndescription: parent\n---\nRun /prose-dep first, then see [[prose-wiki-dep]]. Ignore /usr/bin and /unknown-skill.`,
    );
    const slashDep = await createSkill(repoSkillsDir, "prose-dep");
    const wikiDep = await createSkill(repoSkillsDir, "prose-wiki-dep");
    const service = makeService();

    const resolved = await service.resolveSkillBundleDependencies([
      ref("prose-parent", primary),
    ]);

    expect(resolved.map((r) => r.name)).toEqual([
      "prose-parent",
      "prose-dep",
      "prose-wiki-dep",
    ]);
    expect(resolved.map((r) => r.path)).toEqual([primary, slashDep, wikiDep]);
  });

  it("prefers a dependency beside the referencing skill over a same-named skill elsewhere", async () => {
    const primary = await createSkill(
      repoSkillsDir,
      "scoped-parent",
      withDeps("scoped-parent", ["helper"]),
    );
    const repoHelper = await createSkill(repoSkillsDir, "helper");
    await mkdir(userSkillsHome.dir, { recursive: true });
    await createSkill(userSkillsHome.dir, "helper");
    const service = makeService();

    const resolved = await service.resolveSkillBundleDependencies([
      ref("scoped-parent", primary),
    ]);

    expect(resolved.map((r) => r.path)).toEqual([primary, repoHelper]);
  });

  it("expands a tagged skill to include its transitive dependencies", async () => {
    const primary = await createSkill(
      repoSkillsDir,
      "rs-self-review",
      withDeps("rs-self-review", ["rs-adversarial-review"]),
    );
    const dep = await createSkill(
      repoSkillsDir,
      "rs-adversarial-review",
      withDeps("rs-adversarial-review", ["rs-shared"]),
    );
    const transitive = await createSkill(repoSkillsDir, "rs-shared");
    const service = makeService();

    const resolved = await service.resolveSkillBundleDependencies([
      ref("rs-self-review", primary),
    ]);

    expect(resolved.map((r) => r.name)).toEqual([
      "rs-self-review",
      "rs-adversarial-review",
      "rs-shared",
    ]);
    expect(resolved.map((r) => r.path)).toEqual([primary, dep, transitive]);
  });

  it("does not bundle a dependency that resolves to a built-in skill", async () => {
    const primary = await createSkill(
      repoSkillsDir,
      "needs-builtin",
      withDeps("needs-builtin", ["bundled-skill"]),
    );
    await createSkill(path.join(pluginPath, "skills"), "bundled-skill");
    const service = makeService();

    const resolved = await service.resolveSkillBundleDependencies([
      ref("needs-builtin", primary),
    ]);

    expect(resolved.map((r) => r.name)).toEqual(["needs-builtin"]);
  });

  it("terminates on a dependency cycle without duplicating skills", async () => {
    const a = await createSkill(
      repoSkillsDir,
      "cycle-a",
      withDeps("cycle-a", ["cycle-b"]),
    );
    const b = await createSkill(
      repoSkillsDir,
      "cycle-b",
      withDeps("cycle-b", ["cycle-a"]),
    );
    const service = makeService();

    const resolved = await service.resolveSkillBundleDependencies([
      ref("cycle-a", a),
    ]);

    expect(resolved.map((r) => r.name).sort()).toEqual(["cycle-a", "cycle-b"]);
    expect(resolved.map((r) => r.path).sort()).toEqual([a, b].sort());
  });

  it("throws instead of silently truncating an oversized dependency graph", async () => {
    // A linear chain longer than the 50-skill ceiling.
    const chainLength = 55;
    let firstPath = "";
    for (let i = 0; i < chainLength; i++) {
      const deps = i < chainLength - 1 ? [`chain-${i + 1}`] : [];
      const skillPath = await createSkill(
        repoSkillsDir,
        `chain-${i}`,
        withDeps(`chain-${i}`, deps),
      );
      if (i === 0) firstPath = skillPath;
    }
    const service = makeService();

    await expect(
      service.resolveSkillBundleDependencies([ref("chain-0", firstPath)]),
    ).rejects.toThrow(/exceeds the 50-skill limit/);
  });
});
