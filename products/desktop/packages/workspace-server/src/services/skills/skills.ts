import * as fs from "node:fs";
import * as path from "node:path";
import { SKILL_EXISTS_MARKER, stripFrontmatter } from "@posthog/shared";
import { inject, injectable } from "inversify";
import { WATCHER_SERVICE } from "../../di/tokens";
import type { FoldersService } from "../folders/folders";
import { FOLDERS_SERVICE } from "../folders/identifiers";
import {
  getCodexSkillsDir,
  readCodexMirrorState,
} from "../posthog-plugin/codex-mirror";
import { POSTHOG_PLUGIN_SERVICE } from "../posthog-plugin/identifiers";
import type { PosthogPluginService } from "../posthog-plugin/posthog-plugin";
import type { WatcherService } from "../watcher/service";
import {
  parseSkillDependencies,
  parseSkillFrontmatter,
} from "./parse-skill-frontmatter";
import { parseSkillReferences } from "./parse-skill-references";
import type {
  BundleLocalSkillInput,
  BundleLocalSkillOutput,
  CreateSkillInput,
  ExportedSkill,
  InstallTeamSkillInput,
  SkillBundleRef,
  SkillContents,
  SkillInfo,
  SkillSource,
  UploadableSkillSource,
} from "./schemas";
import { bundleLocalSkill } from "./skill-bundler";
import {
  getMarketplaceInstallPaths,
  getUserSkillsDir,
  isProbablyText,
  listSkillFiles,
  readSkillMetadataFromDir,
} from "./skill-discovery";
import { serializeSkillMarkdown } from "./write-skill-frontmatter";

const MAX_SKILL_FILES = 500;
const MAX_SKILL_FILE_BYTES = 2 * 1024 * 1024;
const SKILLS_WATCH_DEBOUNCE_MS = 300;
const MISSING_DIR_POLL_MS = 2000;
const SKILL_DIR_NAME_PATTERN = /^[a-z0-9][a-z0-9._-]*$/;
const MAX_SKILL_DIR_NAME_LENGTH = 64;

const SKILL_MD_TEMPLATE_BODY = `Explain when this skill applies and how to use it.

## Instructions

1. ...
`;

interface SkillRoot {
  dir: string;
  source: SkillSource;
  repoName?: string;
}

@injectable()
export class SkillsService {
  constructor(
    @inject(POSTHOG_PLUGIN_SERVICE)
    private readonly plugin: PosthogPluginService,
    @inject(FOLDERS_SERVICE)
    private readonly folders: FoldersService,
    @inject(WATCHER_SERVICE)
    private readonly watcher: WatcherService,
  ) {}

  async listSkills(): Promise<SkillInfo[]> {
    const roots = await this.getSkillRoots();
    const results = await Promise.all(
      roots.map((root) =>
        readSkillMetadataFromDir(root.dir, root.source, root.repoName),
      ),
    );
    const skills = results.flat();
    const mirrorState = await readCodexMirrorState(getCodexSkillsDir());
    return dedupeCodexSkills(skills, new Set(mirrorState.mirrored));
  }

  async getSkillContents(skillPath: string): Promise<SkillContents> {
    const skillDir = await this.resolveKnownSkillDir(skillPath);
    const files = await listSkillFiles(skillDir, MAX_SKILL_FILES);
    return { files };
  }

  async readSkillFile(
    skillPath: string,
    filePath: string,
  ): Promise<string | null> {
    const skillDir = await this.resolveKnownSkillDir(skillPath);
    const resolved = resolveSkillFilePath(skillDir, filePath);
    try {
      // realpath also catches escapes via symlinked intermediate directories.
      const [realFile, realDir] = await Promise.all([
        fs.promises.realpath(resolved),
        fs.promises.realpath(skillDir),
      ]);
      if (!realFile.startsWith(realDir + path.sep)) return null;
      const stat = await fs.promises.stat(realFile);
      if (!stat.isFile() || stat.size > MAX_SKILL_FILE_BYTES) return null;
      return await fs.promises.readFile(realFile, "utf-8");
    } catch {
      return null;
    }
  }

  async createSkill(options: CreateSkillInput): Promise<{ path: string }> {
    const name = options.name.trim();
    validateSkillDirName(name);

    const root = await this.resolveWritableRoot(
      options.scope,
      options.repoPath,
    );
    const skillPath = path.join(root, name);
    if (fs.existsSync(skillPath)) {
      throw new Error(`A skill named "${name}" ${SKILL_EXISTS_MARKER}`);
    }

    await fs.promises.mkdir(skillPath, { recursive: true });
    await fs.promises.writeFile(
      path.join(skillPath, "SKILL.md"),
      serializeSkillMarkdown({ name, description: "" }, SKILL_MD_TEMPLATE_BODY),
      "utf-8",
    );
    return { path: skillPath };
  }

  async saveSkillManifest(
    skillPath: string,
    manifest: { name: string; description: string; body: string },
  ): Promise<void> {
    const skillDir = await this.resolveWritableSkillDir(skillPath);
    const content = serializeSkillMarkdown(
      { name: manifest.name.trim(), description: manifest.description.trim() },
      manifest.body,
    );
    // The writer and parser must agree, or the skill vanishes from the list.
    if (!parseSkillFrontmatter(content)) {
      throw new Error("Skill name is required");
    }
    await fs.promises.writeFile(
      path.join(skillDir, "SKILL.md"),
      content,
      "utf-8",
    );
  }

  async saveSkillFile(
    skillPath: string,
    filePath: string,
    content: string,
  ): Promise<void> {
    const skillDir = await this.resolveWritableSkillDir(skillPath);
    const target = resolveSkillFilePath(skillDir, filePath);
    await fs.promises.mkdir(path.dirname(target), { recursive: true });
    await fs.promises.writeFile(target, content, "utf-8");
  }

  async renameSkillFile(
    skillPath: string,
    fromPath: string,
    toPath: string,
  ): Promise<void> {
    const skillDir = await this.resolveWritableSkillDir(skillPath);
    const from = resolveSkillFilePath(skillDir, fromPath);
    const to = resolveSkillFilePath(skillDir, toPath);
    if (from === path.join(skillDir, "SKILL.md")) {
      throw new Error("SKILL.md cannot be renamed");
    }
    if (fs.existsSync(to)) {
      throw new Error(`"${toPath}" already exists`);
    }
    await fs.promises.mkdir(path.dirname(to), { recursive: true });
    await fs.promises.rename(from, to);
  }

  async deleteSkillFile(skillPath: string, filePath: string): Promise<void> {
    const skillDir = await this.resolveWritableSkillDir(skillPath);
    const target = resolveSkillFilePath(skillDir, filePath);
    if (target === path.join(skillDir, "SKILL.md")) {
      throw new Error("SKILL.md cannot be deleted");
    }
    await fs.promises.rm(target, { force: true });
  }

  async deleteSkill(skillPath: string): Promise<void> {
    const skillDir = await this.resolveWritableSkillDir(skillPath);
    await fs.promises.rm(skillDir, { recursive: true, force: true });
  }

  /**
   * Imports a Codex-authored skill into ~/.claude/skills, after which it is
   * an ordinary editable user skill. The original Codex copy is left untouched.
   */
  async importCodexSkill(
    skillPath: string,
    overwrite = false,
  ): Promise<{ path: string }> {
    const resolved = path.resolve(skillPath);
    const codexRoot = path.resolve(getCodexSkillsDir());
    if (
      path.dirname(resolved) !== codexRoot ||
      !fs.existsSync(path.join(resolved, "SKILL.md"))
    ) {
      throw new Error("Access denied: not a Codex skill directory");
    }
    const name = path.basename(resolved);
    validateSkillDirName(name);

    const target = path.join(getUserSkillsDir(), name);
    if (fs.existsSync(target) && !overwrite) {
      throw new Error(
        `A skill named "${name}" ${SKILL_EXISTS_MARKER}. Importing will replace your local version.`,
      );
    }
    if (fs.existsSync(target)) {
      await fs.promises.rm(target, { recursive: true, force: true });
    }
    await fs.promises.mkdir(path.dirname(target), { recursive: true });
    await fs.promises.cp(resolved, target, {
      recursive: true,
      dereference: true,
    });
    return { path: target };
  }

  /**
   * Reads a writable skill directory into a publishable shape: frontmatter
   * split out, body without frontmatter, and every text companion file.
   * Binary or oversized files are skipped and reported.
   */
  async exportSkill(skillPath: string): Promise<ExportedSkill> {
    const skillDir = await this.resolveWritableSkillDir(skillPath);
    const manifest = await fs.promises.readFile(
      path.join(skillDir, "SKILL.md"),
      "utf-8",
    );
    const frontmatter = parseSkillFrontmatter(manifest);
    const name = frontmatter?.name ?? path.basename(skillDir);
    const description = frontmatter?.description ?? "";
    const body = stripFrontmatter(manifest);

    const entries = (await listSkillFiles(skillDir, MAX_SKILL_FILES)).filter(
      (entry) => entry.path !== "SKILL.md",
    );
    const results = await Promise.all(
      entries.map(async (entry) => {
        if (entry.size > MAX_SKILL_FILE_BYTES) {
          return { path: entry.path, content: null };
        }
        const bytes = await fs.promises.readFile(
          path.join(skillDir, ...entry.path.split("/")),
        );
        return {
          path: entry.path,
          content: isProbablyText(bytes) ? bytes.toString("utf-8") : null,
        };
      }),
    );

    return {
      name,
      description,
      body,
      files: results.filter(
        (r): r is { path: string; content: string } => r.content !== null,
      ),
      skipped: results.filter((r) => r.content === null).map((r) => r.path),
    };
  }

  /**
   * Materializes a team skill into ~/.claude/skills (agents need files on
   * disk). From then on it follows the same copy-and-forget rule as
   * marketplace installs.
   */
  async installTeamSkill(
    input: InstallTeamSkillInput,
  ): Promise<{ path: string }> {
    const name = input.name.trim();
    validateSkillDirName(name);
    const userRoot = getUserSkillsDir();
    const target = path.join(userRoot, name);
    if (fs.existsSync(target) && !input.overwrite) {
      throw new Error(
        `A skill named "${name}" ${SKILL_EXISTS_MARKER}. Installing will replace your local version.`,
      );
    }

    // Stage first: a bad payload must not corrupt or delete the existing skill.
    await fs.promises.mkdir(userRoot, { recursive: true });
    const staging = await fs.promises.mkdtemp(
      path.join(userRoot, `.install-${name}-`),
    );
    const previous = `${staging}-previous`;
    try {
      await fs.promises.writeFile(
        path.join(staging, "SKILL.md"),
        serializeSkillMarkdown(
          { name, description: input.description },
          input.body,
        ),
        "utf-8",
      );
      await Promise.all(
        input.files.map(async (file) => {
          const filePath = resolveSkillFilePath(staging, file.path);
          await fs.promises.mkdir(path.dirname(filePath), { recursive: true });
          await fs.promises.writeFile(filePath, file.content, "utf-8");
        }),
      );

      const hadExisting = fs.existsSync(target);
      if (hadExisting) {
        await fs.promises.rename(target, previous);
      }
      try {
        await fs.promises.rename(staging, target);
      } catch (error) {
        if (hadExisting) {
          await fs.promises.rename(previous, target).catch(() => {});
        }
        throw error;
      }
      await fs.promises.rm(previous, { recursive: true, force: true });
    } catch (error) {
      await fs.promises.rm(staging, { recursive: true, force: true });
      throw error;
    }
    return { path: target };
  }

  /**
   * Emits a debounced "skills changed" event whenever anything inside the
   * writable skill roots changes on disk (external editors, agent sessions,
   * `touch` from a terminal, ...).
   */
  async *watchSkills(signal?: AbortSignal): AsyncGenerator<{ changed: true }> {
    const userRoot = getUserSkillsDir();
    // The user root is ours to create; missing repo roots are polled for.
    await fs.promises.mkdir(userRoot, { recursive: true }).catch(() => {});
    const folders = await this.folders.getFolders();
    const dirs = [
      userRoot,
      ...folders.map((f) => path.join(f.path, ".claude", "skills")),
    ];

    yield* this.watchSkillDirs(dirs, signal);
  }

  /**
   * Merges watchers over the given directories into one debounced stream.
   * Directories that don't exist yet are polled until they appear.
   */
  async *watchSkillDirs(
    dirs: string[],
    signal?: AbortSignal,
  ): AsyncGenerator<{ changed: true }> {
    if (dirs.length === 0) return;

    let pending = false;
    let finished = 0;
    let notify: (() => void) | undefined;
    const wake = () => notify?.();

    for (const dir of dirs) {
      void (async () => {
        try {
          if (!(await dirExists(dir))) {
            if (!(await waitForDir(dir, signal))) return;
            pending = true;
            wake();
          }
          for await (const _batch of this.watcher.watch(dir, {}, signal)) {
            pending = true;
            wake();
          }
        } catch {
          // A failed watcher on one root must not break the others.
        } finally {
          finished++;
          wake();
        }
      })();
    }

    while (finished < dirs.length && !signal?.aborted) {
      if (!pending) {
        await new Promise<void>((resolve) => {
          notify = resolve;
        });
        notify = undefined;
        continue;
      }
      // Collapse bursts of file events into a single notification.
      await delay(SKILLS_WATCH_DEBOUNCE_MS, signal);
      if (signal?.aborted) return;
      pending = false;
      yield { changed: true };
    }
  }

  private async getSkillRoots(): Promise<SkillRoot[]> {
    const pluginPath = this.plugin.getPluginPath();
    const folders = await this.folders.getFolders();
    const marketplacePaths = await getMarketplaceInstallPaths();

    return [
      { dir: path.join(pluginPath, "skills"), source: "bundled" as const },
      { dir: getUserSkillsDir(), source: "user" as const },
      ...folders.map((f) => ({
        dir: path.join(f.path, ".claude", "skills"),
        source: "repo" as const,
        repoName: f.name,
      })),
      ...marketplacePaths.map((p) => ({
        dir: path.join(p, "skills"),
        source: "marketplace" as const,
      })),
      { dir: getCodexSkillsDir(), source: "codex" as const },
    ];
  }

  /**
   * Validates that the given path is a skill directory directly under one of
   * the discovery roots. This keeps the contents/readFile endpoints from
   * becoming arbitrary-filesystem reads.
   */
  private async resolveKnownSkillDir(skillPath: string): Promise<string> {
    const resolved = path.resolve(skillPath);
    const roots = await this.getSkillRoots();
    const parent = path.dirname(resolved);
    const isUnderKnownRoot = roots.some(
      (root) => path.resolve(root.dir) === parent,
    );
    const hasSkillMd =
      isUnderKnownRoot &&
      (await fs.promises
        .access(path.join(resolved, "SKILL.md"))
        .then(() => true)
        .catch(() => false));
    if (!hasSkillMd) {
      throw new Error("Access denied: not a known skill directory");
    }
    return resolved;
  }

  private async getWritableRoots(): Promise<string[]> {
    const folders = await this.folders.getFolders();
    return [
      getUserSkillsDir(),
      ...folders.map((f) => path.join(f.path, ".claude", "skills")),
    ];
  }

  private async resolveWritableRoot(
    scope: "user" | "repo",
    repoPath: string | undefined,
  ): Promise<string> {
    if (scope === "user") {
      return getUserSkillsDir();
    }
    const folders = await this.folders.getFolders();
    const folder = folders.find(
      (f) => repoPath && path.resolve(f.path) === path.resolve(repoPath),
    );
    if (!folder) {
      throw new Error("Access denied: not an open workspace folder");
    }
    return path.join(folder.path, ".claude", "skills");
  }

  /**
   * Hard guard for every mutation: the target must be a skill directory
   * directly under a writable root (the user's `~/.claude/skills` or a
   * workspace folder's `.claude/skills`). Bundled skills, plugin install
   * paths, and anything else are rejected here, not in the UI.
   */
  private async resolveWritableSkillDir(skillPath: string): Promise<string> {
    const resolved = path.resolve(skillPath);
    const roots = await this.getWritableRoots();
    const parent = path.dirname(resolved);
    if (!roots.some((root) => path.resolve(root) === parent)) {
      throw new Error("Access denied: skill is not in a writable location");
    }
    if (!fs.existsSync(path.join(resolved, "SKILL.md"))) {
      throw new Error("Access denied: not a known skill directory");
    }
    return resolved;
  }

  async bundleLocalSkill(
    input: BundleLocalSkillInput,
  ): Promise<BundleLocalSkillOutput> {
    const skillDir = await this.resolveKnownSkillDir(input.path);
    await this.assertRepoSkillStaysInRepo(skillDir);
    return bundleLocalSkill({
      name: input.name,
      source: input.source,
      skillPath: skillDir,
    });
  }

  /**
   * A repository can commit any ancestor of its skills (`.claude` or
   * `.claude/skills`) as a symlink pointing outside the repo, which passes the
   * lexical known-root check and the bundler's leaf-symlink check yet bundles
   * an external directory. Uploads must stay inside the real repository, so
   * anchor the check on the workspace folder itself — the one path segment a
   * repo author cannot control.
   */
  private async assertRepoSkillStaysInRepo(skillDir: string): Promise<void> {
    const parent = path.dirname(skillDir);
    const folders = await this.folders.getFolders();
    const owningFolder = folders.find(
      (folder) =>
        path.resolve(path.join(folder.path, ".claude", "skills")) === parent,
    );
    if (!owningFolder) return;
    const [realSkill, realFolder] = await Promise.all([
      fs.promises.realpath(skillDir),
      fs.promises.realpath(path.resolve(owningFolder.path)),
    ]);
    if (!realSkill.startsWith(realFolder + path.sep)) {
      throw new Error(
        "Access denied: repository skill resolves outside its repository",
      );
    }
  }

  /**
   * Expand a set of tagged skill refs to include their transitive dependency
   * skills, so a skill that needs another pulls it into the same cloud run.
   * A dependency is either declared (SKILL.md frontmatter `dependencies:`)
   * or referenced in the SKILL.md body as `/skill-name` or `[[skill-name]]`.
   * Only uploadable local skills are returned; a dependency that resolves to
   * a built-in (`bundled`) skill is already in the sandbox and is skipped.
   */
  async resolveSkillBundleDependencies(
    refs: SkillBundleRef[],
  ): Promise<SkillBundleRef[]> {
    if (refs.length === 0) return [];

    const allSkills = await this.listSkills();
    // Prefer a dependency beside the referencing skill (same root), then one
    // from the same source, so a repo skill referencing /helper gets its
    // sibling rather than a same-named skill from another source.
    const findUploadableByName = (
      name: string,
      referencedFrom: SkillBundleRef,
    ): SkillBundleRef | null => {
      const candidates = allSkills.filter(
        (skill) => skill.name === name && isUploadableSkillSource(skill.source),
      );
      const match =
        candidates.find(
          (skill) =>
            path.dirname(skill.path) === path.dirname(referencedFrom.path),
        ) ??
        candidates.find((skill) => skill.source === referencedFrom.source) ??
        candidates[0];
      return match && isUploadableSkillSource(match.source)
        ? { name: match.name, source: match.source, path: match.path }
        : null;
    };
    const knownSkillNames: ReadonlySet<string> = new Set(
      allSkills.map((skill) => skill.name),
    );

    const seen = new Set<string>();
    const resolved: SkillBundleRef[] = [];
    const queue: SkillBundleRef[] = [...refs];
    // Sanity ceiling on the dependency closure. The `seen` set already
    // guarantees termination, so exceeding this means a pathological graph —
    // throw loudly rather than silently uploading an arbitrary subset and
    // leaving the run missing skills it was told to include.
    const MAX_RESOLVED_SKILLS = 50;

    while (queue.length > 0) {
      const ref = queue.shift();
      if (!ref) break;
      const key = `${ref.source}:${ref.path}`;
      if (seen.has(key)) continue;
      if (resolved.length >= MAX_RESOLVED_SKILLS) {
        throw new Error(
          `Skill dependency graph exceeds the ${MAX_RESOLVED_SKILLS}-skill limit for a single cloud run ` +
            `(from: ${refs.map((r) => r.name).join(", ")}). Reduce the tagged skills or their dependencies.`,
        );
      }
      seen.add(key);
      resolved.push(ref);

      let dependencyNames: string[] = [];
      try {
        const skillDir = await this.resolveKnownSkillDir(ref.path);
        const manifest = await fs.promises.readFile(
          path.join(skillDir, "SKILL.md"),
          "utf-8",
        );
        dependencyNames = [
          ...new Set([
            ...parseSkillDependencies(manifest),
            ...parseSkillReferences(manifest, knownSkillNames),
          ]),
        ];
      } catch {
        // A ref we can't read (missing/renamed skill) still uploads on its own;
        // just skip its dependency expansion rather than failing the whole run.
        continue;
      }

      for (const dependencyName of dependencyNames) {
        const dependencyRef = findUploadableByName(dependencyName, ref);
        if (
          dependencyRef &&
          !seen.has(`${dependencyRef.source}:${dependencyRef.path}`)
        ) {
          queue.push(dependencyRef);
        }
      }
    }

    return resolved;
  }
}

function isUploadableSkillSource(
  source: SkillSource,
): source is UploadableSkillSource {
  return source !== "bundled";
}

export function validateSkillDirName(name: string): void {
  if (
    !SKILL_DIR_NAME_PATTERN.test(name) ||
    name.length > MAX_SKILL_DIR_NAME_LENGTH
  ) {
    throw new Error(
      "Skill names must be lowercase letters, numbers, dots, dashes, or underscores",
    );
  }
}

function dirExists(dir: string): Promise<boolean> {
  return fs.promises
    .access(dir)
    .then(() => true)
    .catch(() => false);
}

/** Polls until the directory exists. Resolves false if aborted first. */
async function waitForDir(dir: string, signal?: AbortSignal): Promise<boolean> {
  while (!signal?.aborted) {
    if (await dirExists(dir)) return true;
    await delay(MISSING_DIR_POLL_MS, signal);
  }
  return false;
}

/**
 * Hides Codex copies already represented elsewhere in the list: a bundled skill
 * synced there by the old pipeline, a legacy mirror copy, or a skill the user
 * has imported into their own `~/.claude/skills`. What remains is genuinely the
 * user's Codex-only skills.
 */
function dedupeCodexSkills(
  skills: SkillInfo[],
  mirroredNames: Set<string>,
): SkillInfo[] {
  const bundledNames = new Set(
    skills.filter((s) => s.source === "bundled").map((s) => s.name),
  );
  const userDirNames = new Set(
    skills.filter((s) => s.source === "user").map((s) => path.basename(s.path)),
  );
  return skills.filter((skill) => {
    if (skill.source !== "codex") return true;
    const dirName = path.basename(skill.path);
    // The mirror state and the user's own skills are matched by directory name;
    // bundled copies keep their frontmatter name verbatim, so match those by it.
    return (
      !bundledNames.has(skill.name) &&
      !mirroredNames.has(dirName) &&
      !userDirNames.has(dirName)
    );
  });
}

function delay(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve) => {
    const timer = setTimeout(done, ms);
    function done() {
      signal?.removeEventListener("abort", done);
      clearTimeout(timer);
      resolve();
    }
    signal?.addEventListener("abort", done, { once: true });
  });
}

function resolveSkillFilePath(skillDir: string, filePath: string): string {
  const resolved = path.resolve(skillDir, filePath);
  if (resolved === skillDir || !resolved.startsWith(skillDir + path.sep)) {
    throw new Error("Access denied: path outside skill directory");
  }
  return resolved;
}
