import { execSync } from "node:child_process";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { GitService } from "./service";

function run(cmd: string, cwd: string): void {
  execSync(cmd, { cwd, stdio: "pipe" });
}

async function createTempGitRepo(remoteUrl?: string): Promise<string> {
  const dir = await fs.mkdtemp(path.join(os.tmpdir(), "git-it-"));
  run("git init -b main", dir);
  run("git config user.email 'test@test.com'", dir);
  run("git config user.name 'Test'", dir);
  run("git config commit.gpgsign false", dir);
  if (remoteUrl) {
    run(`git remote add origin ${remoteUrl}`, dir);
  }
  await fs.writeFile(path.join(dir, "README.md"), "# Test Repo\n");
  run("git add .", dir);
  run("git commit -m 'Initial commit'", dir);
  return dir;
}

async function createBareRemote(): Promise<string> {
  const dir = await fs.mkdtemp(path.join(os.tmpdir(), "git-bare-"));
  run("git init --bare -b main", dir);
  return dir;
}

function commitAll(repoDir: string, message: string): void {
  execSync(
    `git -C ${repoDir} add . && git -C ${repoDir} commit -m '${message}'`,
    { stdio: "pipe" },
  );
}

describe("GitService integration (git-read + git-mutate)", () => {
  let git: GitService;
  let repo: string;
  const dirs: string[] = [];

  beforeEach(async () => {
    git = new GitService();
    repo = await createTempGitRepo();
    dirs.push(repo);
  });

  afterEach(async () => {
    await Promise.all(
      dirs.splice(0).map((d) => fs.rm(d, { recursive: true, force: true })),
    );
  });

  describe("validateRepo", () => {
    it("is true inside a git repo", async () => {
      expect(await git.validateRepo(repo)).toBe(true);
    });

    it("is false for a non-repo directory", async () => {
      const plain = await fs.mkdtemp(path.join(os.tmpdir(), "git-it-plain-"));
      dirs.push(plain);
      expect(await git.validateRepo(plain)).toBe(false);
    });

    it("is false for an empty path", async () => {
      expect(await git.validateRepo("")).toBe(false);
    });
  });

  describe("read ops", () => {
    it("getCurrentBranch returns the checked-out branch", async () => {
      expect(await git.getCurrentBranch(repo)).toBe("main");
    });

    it("getDefaultBranch resolves to main offline", async () => {
      expect(await git.getDefaultBranch(repo)).toBe("main");
    });

    it("getLatestCommit returns the initial commit", async () => {
      const commit = await git.getLatestCommit(repo);
      expect(commit?.message).toBe("Initial commit");
    });

    it("getFileAtHead returns committed content", async () => {
      expect(await git.getFileAtHead(repo, "README.md")).toBe("# Test Repo\n");
    });

    it("getGitBusyState is not busy on a clean repo", async () => {
      expect(await git.getGitBusyState(repo)).toEqual({ busy: false });
    });

    it("getGitSyncStatus reports no remote", async () => {
      const status = await git.getGitSyncStatus(repo);
      expect(status.hasRemote).toBe(false);
    });
  });

  describe("detectRepo / getGitRepoInfo (github remote, offline)", () => {
    it("detectRepo parses org + repo from the remote", async () => {
      const remoteRepo = await createTempGitRepo(
        "https://github.com/posthog/posthog.git",
      );
      dirs.push(remoteRepo);

      const result = await git.detectRepo(remoteRepo);
      expect(result).toMatchObject({
        organization: "posthog",
        repository: "posthog",
        branch: "main",
      });
    });

    it("getGitRepoInfo parses org + repo from the remote", async () => {
      const remoteRepo = await createTempGitRepo(
        "https://github.com/posthog/posthog.git",
      );
      dirs.push(remoteRepo);

      const info = await git.getGitRepoInfo(remoteRepo);
      expect(info).toMatchObject({
        organization: "posthog",
        repository: "posthog",
        currentBranch: "main",
        defaultBranch: "main",
      });
    });
  });

  describe("branch mutation", () => {
    it("createBranch creates and switches to the new branch", async () => {
      await git.createBranch(repo, "feature");
      expect(await git.getAllBranches(repo)).toContain("feature");
      expect(await git.getCurrentBranch(repo)).toBe("feature");
    });

    it("checkoutBranch switches back and reports the previous branch", async () => {
      await git.createBranch(repo, "feature");

      const result = await git.checkoutBranch(repo, "main");
      expect(result).toEqual({
        previousBranch: "feature",
        currentBranch: "main",
      });
      expect(await git.getCurrentBranch(repo)).toBe("main");
    });
  });

  describe("staging mutation", () => {
    it("getChangedFilesHead lists a new untracked file", async () => {
      await fs.writeFile(path.join(repo, "new.txt"), "hello\n");
      const files = await git.getChangedFilesHead(repo);
      expect(files.map((f) => f.path)).toContain("new.txt");
    });

    it("stageFiles marks the file staged in the returned snapshot", async () => {
      await fs.writeFile(path.join(repo, "new.txt"), "hello\n");
      const snapshot = await git.stageFiles(repo, ["new.txt"]);
      const staged = snapshot.changedFiles?.find((f) => f.path === "new.txt");
      expect(staged?.staged).toBe(true);
    });

    it("unstageFiles clears the staged flag", async () => {
      await fs.writeFile(path.join(repo, "new.txt"), "hello\n");
      await git.stageFiles(repo, ["new.txt"]);
      const snapshot = await git.unstageFiles(repo, ["new.txt"]);
      const entry = snapshot.changedFiles?.find((f) => f.path === "new.txt");
      expect(entry).toBeDefined();
      expect(entry?.staged).toBeFalsy();
    });
  });

  describe("commit", () => {
    it("commits staged changes and reports the sha and branch", async () => {
      await fs.writeFile(path.join(repo, "feature.txt"), "feature\n");
      await git.stageFiles(repo, ["feature.txt"]);

      const result = await git.commit(repo, "add feature");

      expect(result.success).toBe(true);
      expect(result.commitSha).toMatch(/^[0-9a-f]{7,}$/);
      expect(result.branch).toBe("main");
      // The file is committed -> no longer a working-tree change against HEAD.
      const files = await git.getChangedFilesHead(repo);
      expect(files.map((f) => f.path)).not.toContain("feature.txt");
    });

    it("rejects an empty commit message", async () => {
      const result = await git.commit(repo, "   ");
      expect(result.success).toBe(false);
      expect(result.message).toMatch(/message is required/i);
      expect(result.commitSha).toBeNull();
    });

    it("threads a passed env through without breaking the commit", async () => {
      await fs.writeFile(path.join(repo, "env.txt"), "env\n");
      await git.stageFiles(repo, ["env.txt"]);

      const result = await git.commit(repo, "with env", {
        env: { POSTHOG_TEST_ENV: "1" },
      });

      expect(result.success).toBe(true);
      expect(result.commitSha).toBeTruthy();
    });
  });

  describe("diff ops", () => {
    it("getDiffUnstaged includes the working-tree change", async () => {
      await fs.writeFile(path.join(repo, "README.md"), "# Test Repo\nmore\n");
      const diff = await git.getDiffUnstaged(repo);
      expect(diff).toContain("more");
    });

    it("getDiffCached includes staged changes", async () => {
      await fs.writeFile(path.join(repo, "README.md"), "# Test Repo\nstaged\n");
      run("git add README.md", repo);
      const diff = await git.getDiffCached(repo);
      expect(diff).toContain("staged");
    });

    it("getDiffStats counts changed files", async () => {
      await fs.writeFile(path.join(repo, "README.md"), "# Test Repo\nchange\n");
      const stats = await git.getDiffStats(repo);
      expect(stats.filesChanged).toBeGreaterThanOrEqual(1);
    });
  });

  describe("discardFileChanges", () => {
    it("restores a modified tracked file", async () => {
      await fs.writeFile(path.join(repo, "README.md"), "# Test Repo\ndirty\n");
      const result = await git.discardFileChanges(
        repo,
        "README.md",
        "modified",
      );
      expect(result.success).toBe(true);
      expect(await git.getFileAtHead(repo, "README.md")).toBe("# Test Repo\n");
      const onDisk = await fs.readFile(path.join(repo, "README.md"), "utf-8");
      expect(onDisk).toBe("# Test Repo\n");
    });
  });

  describe("remote mutation (local bare remote, offline)", () => {
    let bare: string;
    let work: string;

    beforeEach(async () => {
      bare = await createBareRemote();
      work = await createTempGitRepo(bare);
      dirs.push(bare, work);
      run("git push -u origin main", work);
    });

    it("push uploads new commits to the remote", async () => {
      await fs.writeFile(path.join(work, "a.txt"), "x\n");
      commitAll(work, "add a");

      const result = await git.push(work, "origin");
      expect(result.success).toBe(true);
      expect(result.message).toContain("Pushed");
    });

    it("publish pushes a new branch and sets upstream", async () => {
      await git.createBranch(work, "feature");
      await fs.writeFile(path.join(work, "f.txt"), "y\n");
      commitAll(work, "add f");

      const result = await git.publish(work, "origin");
      expect(result.success).toBe(true);
      expect(result.branch).toBe("feature");
    });

    it("pull fetches commits pushed by another clone", async () => {
      const clone = await fs.mkdtemp(path.join(os.tmpdir(), "git-clone-"));
      dirs.push(clone);
      run(`git clone ${bare} ${clone}`, os.tmpdir());
      run("git config user.email 'c@test.com'", clone);
      run("git config user.name 'Clone'", clone);

      await fs.writeFile(path.join(work, "shared.txt"), "from-work\n");
      commitAll(work, "add shared");
      await git.push(work, "origin");

      const result = await git.pull(clone, "origin");
      expect(result.success).toBe(true);
      expect(
        await fs
          .readFile(path.join(clone, "shared.txt"), "utf-8")
          .catch(() => null),
      ).toBe("from-work\n");
    });

    it("sync pulls then pushes successfully", async () => {
      await fs.writeFile(path.join(work, "s.txt"), "z\n");
      commitAll(work, "add s");

      const result = await git.sync(work, "origin");
      expect(result.success).toBe(true);
    });

    it("getGitSyncStatus does not fetch by default, fetches when fetchFromRemote=true", async () => {
      // Another clone pushes a commit. The original `work` repo only learns
      // about it after a fetch — so this lets us tell whether a sync-status
      // read touched the network or not.
      const otherClone = await fs.mkdtemp(path.join(os.tmpdir(), "git-other-"));
      dirs.push(otherClone);
      run(`git clone ${bare} ${otherClone}`, os.tmpdir());
      run("git config user.email 'other@test.com'", otherClone);
      run("git config user.name 'Other'", otherClone);
      run("git config commit.gpgsign false", otherClone);
      await fs.writeFile(
        path.join(otherClone, "remote-only.txt"),
        "from-other\n",
      );
      commitAll(otherClone, "from other clone");
      run("git push origin main", otherClone);

      // Default: no fetch, so `work` still thinks it is at the remote tip.
      const stale = await git.getGitSyncStatus(work);
      expect(stale.behind).toBe(0);

      // Explicit fetch: `work` learns it is one commit behind.
      const fresh = await git.getGitSyncStatus(work, true);
      expect(fresh.behind).toBe(1);

      // A second fetch immediately after must still hit the network — the
      // staleness throttle must never silently swallow an opt-in
      // fetchFromRemote=true call.
      await fs.writeFile(
        path.join(otherClone, "remote-only-2.txt"),
        "from-other-2\n",
      );
      commitAll(otherClone, "from other clone (second)");
      run("git push origin main", otherClone);

      const fresher = await git.getGitSyncStatus(work, true);
      expect(fresher.behind).toBe(2);
    }, 15_000);
  });
});
