import fs from "node:fs";
import path from "node:path";
import {
  ROOT_LOGGER,
  type RootLogger,
  type ScopedLogger,
} from "@posthog/di/logger";
import {
  getLinkedWorktreeMainPath,
  getRemoteUrl,
  isGitRepository,
} from "@posthog/git/queries";
import { InitRepositorySaga } from "@posthog/git/sagas/init";
import { parseGithubUrl } from "@posthog/git/utils";
import { WorktreeManager } from "@posthog/git/worktree";
import { DIALOG_SERVICE, type IDialog } from "@posthog/platform/dialog";
import {
  type IWorkspaceSettings,
  WORKSPACE_SETTINGS_SERVICE,
} from "@posthog/platform/workspace-settings";
import { inject, injectable } from "inversify";
import {
  REPOSITORY_REPOSITORY,
  WORKSPACE_REPOSITORY,
  WORKTREE_REPOSITORY,
} from "../../db/identifiers";
import type {
  IRepositoryRepository,
  Repository,
} from "../../db/repositories/repository-repository";
import type { IWorkspaceRepository } from "../../db/repositories/workspace-repository";
import type { IWorktreeRepository } from "../../db/repositories/worktree-repository";
import type { RegisteredFolder } from "./schemas";

function normalizeRepoKey(key: string): string {
  return key.trim().replace(/\.git$/, "");
}

@injectable()
export class FoldersService {
  constructor(
    @inject(REPOSITORY_REPOSITORY)
    private readonly repositoryRepo: IRepositoryRepository,
    @inject(WORKSPACE_REPOSITORY)
    private readonly workspaceRepo: IWorkspaceRepository,
    @inject(WORKTREE_REPOSITORY)
    private readonly worktreeRepo: IWorktreeRepository,
    @inject(DIALOG_SERVICE)
    private readonly dialog: IDialog,
    @inject(WORKSPACE_SETTINGS_SERVICE)
    private readonly workspaceSettings: IWorkspaceSettings,
    @inject(ROOT_LOGGER)
    rootLogger: RootLogger,
  ) {
    this.log = rootLogger.scope("folders-service");
    this.initialize().catch((err) => {
      this.log.error("Folders initialization failed", err);
    });
  }

  private readonly log: ScopedLogger;

  private async initialize(): Promise<void> {
    const folders = await this.getFolders();

    const deletedFolders = folders.filter((f) => !f.exists);
    if (deletedFolders.length > 0) {
      let removed = 0;
      for (const folder of deletedFolders) {
        try {
          await this.removeFolder(folder.id);
          removed++;
        } catch (err) {
          this.log.error(
            `Failed to remove deleted folder ${folder.path}:`,
            err,
          );
        }
      }
      if (removed > 0) {
        this.log.info(`Removed ${removed} deleted folder(s)`);
      }
    }

    const existingFolders = folders.filter((f) => f.exists);
    const results = await Promise.allSettled(
      existingFolders.map(async (folder) => {
        await this.createWorktreeManager(folder.path).sweepTrash();
        await this.cleanupOrphanedWorktrees(folder.path);
      }),
    );
    for (const [i, result] of results.entries()) {
      if (result.status === "rejected") {
        this.log.error(
          `Failed to clean up worktrees for ${existingFolders[i].path}:`,
          result.reason,
        );
      }
    }
  }

  private createWorktreeManager(mainRepoPath: string): WorktreeManager {
    return new WorktreeManager({
      mainRepoPath,
      worktreeBasePath: this.workspaceSettings.getWorktreeLocation(),
      logger: this.log,
    });
  }

  private getDisplayName(
    repoPath: string,
    remoteUrl: string | null | undefined,
  ): string {
    const localName = path.basename(repoPath);
    if (remoteUrl) {
      const repoName = normalizeRepoKey(remoteUrl).split("/").pop();
      if (repoName && repoName.toLowerCase() !== localName.toLowerCase()) {
        return `${localName} (${repoName})`;
      }
    }
    return localName;
  }

  async getFolders(): Promise<(RegisteredFolder & { exists: boolean })[]> {
    const repos = this.repositoryRepo.findAll();
    return repos
      .filter((r) => r.path)
      .map((r) => ({
        id: r.id,
        path: r.path,
        name: this.getDisplayName(r.path, r.remoteUrl),
        remoteUrl: r.remoteUrl ?? null,
        lastAccessed: r.lastAccessedAt ?? r.createdAt,
        createdAt: r.createdAt,
        mainRepoPath: getLinkedWorktreeMainPath(r.path),
        exists: fs.existsSync(r.path),
      }));
  }

  async addFolder(
    folderPath: string,
    options: { remoteUrl?: string } = {},
  ): Promise<RegisteredFolder & { exists: boolean }> {
    const folderName = path.basename(folderPath);
    if (!folderPath || !folderName) {
      throw new Error(
        `Invalid folder path: "${folderPath}" - path must have a valid directory name`,
      );
    }

    const isRepo = await isGitRepository(folderPath);

    if (!isRepo) {
      const response = await this.dialog.confirm({
        severity: "question",
        title: "Initialize Git Repository",
        message: "This folder is not a git repository",
        detail: `Would you like to initialize git in "${path.basename(folderPath)}"?`,
        options: ["Initialize Git", "Cancel"],
        defaultIndex: 0,
        cancelIndex: 1,
      });

      if (response === 1) {
        throw new Error("Folder must be a git repository");
      }

      const saga = new InitRepositorySaga();
      const initResult = await saga.run({
        baseDir: folderPath,
        initialCommit: true,
        commitMessage: "Initial commit",
      });
      if (!initResult.success) {
        throw new Error(
          `Failed to initialize git repository: ${initResult.error}`,
        );
      }
    }

    const repoKey = await this.resolveRepoKey(folderPath, options.remoteUrl);
    const existingRepo = this.repositoryRepo.findByPath(folderPath);
    let repo: Repository;

    if (existingRepo) {
      this.repositoryRepo.updateLastAccessed(existingRepo.id);
      const updated = this.repositoryRepo.findById(existingRepo.id);
      if (!updated) {
        throw new Error(`Repository ${existingRepo.id} not found after update`);
      }
      repo = updated;

      if (repoKey && repo.remoteUrl !== repoKey) {
        this.repositoryRepo.updateRemoteUrl(repo.id, repoKey);
        const refreshed = this.repositoryRepo.findById(repo.id);
        if (!refreshed) {
          throw new Error(
            `Repository ${repo.id} not found after remote URL update`,
          );
        }
        repo = refreshed;
      }
    } else {
      repo = this.repositoryRepo.create({
        path: folderPath,
        remoteUrl: repoKey ?? undefined,
      });
    }

    return {
      id: repo.id,
      path: repo.path,
      name: this.getDisplayName(repo.path, repo.remoteUrl),
      remoteUrl: repo.remoteUrl ?? null,
      lastAccessed: repo.lastAccessedAt ?? repo.createdAt,
      createdAt: repo.createdAt,
      mainRepoPath: getLinkedWorktreeMainPath(repo.path),
      exists: true,
    };
  }

  async removeFolder(folderId: string): Promise<void> {
    const repo = this.repositoryRepo.findById(folderId);
    if (!repo) {
      this.log.debug(`Folder not found: ${folderId}`);
      return;
    }

    const workspaces = this.workspaceRepo.findAllByRepositoryId(folderId);
    const worktreeBasePath = this.workspaceSettings.getWorktreeLocation();
    const repoName = path.basename(repo.path);

    for (const workspace of workspaces) {
      if (workspace.mode === "worktree") {
        const worktree = this.worktreeRepo.findByWorkspaceId(workspace.id);
        if (worktree) {
          const worktreePath = path.join(
            worktreeBasePath,
            repoName,
            worktree.name,
          );
          try {
            await this.createWorktreeManager(repo.path).deleteWorktree(
              worktreePath,
            );
          } catch (error) {
            this.log.error(`Failed to delete worktree ${worktreePath}:`, error);
          }
        }
      }
    }

    this.repositoryRepo.delete(folderId);
    this.log.debug(`Removed folder with ID: ${folderId}`);
  }

  async updateFolderAccessed(folderId: string): Promise<void> {
    this.repositoryRepo.updateLastAccessed(folderId);
  }

  async cleanupOrphanedWorktrees(mainRepoPath: string): Promise<void> {
    const allWorktrees = this.worktreeRepo.findAll();
    const associatedWorktreePaths = allWorktrees.map((wt) => wt.path);

    await this.createWorktreeManager(mainRepoPath).cleanupOrphanedWorktrees(
      associatedWorktreePaths,
    );
  }

  private async resolveRepoKey(
    folderPath: string,
    overrideRemoteUrl: string | undefined,
  ): Promise<string | null> {
    const slug = (url: string | null | undefined) => {
      const parsed = parseGithubUrl(url);
      return parsed ? `${parsed.owner}/${parsed.repo}` : null;
    };
    if (overrideRemoteUrl) {
      return slug(overrideRemoteUrl) ?? normalizeRepoKey(overrideRemoteUrl);
    }
    const localRemoteUrl = await getRemoteUrl(folderPath);
    return slug(localRemoteUrl);
  }

  getRepositoryByRemoteUrl(
    remoteUrl: string,
  ): { id: string; path: string } | null {
    const repo = this.repositoryRepo.findByRemoteUrl(remoteUrl);
    if (!repo) return null;
    return { id: repo.id, path: repo.path };
  }

  getMostRecentlyAccessedRepository(): { id: string; path: string } | null {
    const repo = this.repositoryRepo.findMostRecentlyAccessed();
    if (!repo) return null;
    return { id: repo.id, path: repo.path };
  }

  async clearAllData(): Promise<void> {
    const workspaces = this.workspaceRepo.findAll();
    const worktreeBasePath = this.workspaceSettings.getWorktreeLocation();

    for (const workspace of workspaces) {
      if (workspace.mode === "worktree" && workspace.repositoryId) {
        const repo = this.repositoryRepo.findById(workspace.repositoryId);
        const worktree = this.worktreeRepo.findByWorkspaceId(workspace.id);
        if (repo && worktree) {
          try {
            const manager = new WorktreeManager({
              mainRepoPath: repo.path,
              worktreeBasePath,
              logger: this.log,
            });
            await manager.deleteWorktree(worktree.path);
          } catch (error) {
            this.log.error(
              `Failed to delete worktree ${worktree.path}:`,
              error,
            );
          }
        }
      }
    }

    this.worktreeRepo.deleteAll();
    this.workspaceRepo.deleteAll();
    this.repositoryRepo.deleteAll();

    this.log.info("Cleared all application data");
  }
}
