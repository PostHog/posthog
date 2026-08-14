import { inject, injectable } from "inversify";
import {
  DEFAULT_ADDITIONAL_DIRECTORY_REPOSITORY,
  WORKSPACE_REPOSITORY,
} from "../../db/identifiers";
import type { IDefaultAdditionalDirectoryRepository } from "../../db/repositories/default-additional-directory-repository";
import type { IWorkspaceRepository } from "../../db/repositories/workspace-repository";

/**
 * Owns the "additional directories" domain: the per-device default directories
 * the agent may always access, and the per-task directories added to a single
 * workspace. Backing service for the additional-directories router, which
 * previously reached two repositories directly (a router-bypasses-service
 * anti-pattern).
 */
@injectable()
export class AdditionalDirectoriesService {
  constructor(
    @inject(DEFAULT_ADDITIONAL_DIRECTORY_REPOSITORY)
    private readonly defaults: IDefaultAdditionalDirectoryRepository,
    @inject(WORKSPACE_REPOSITORY)
    private readonly workspaces: IWorkspaceRepository,
  ) {}

  listDefaults(): string[] {
    return this.defaults.list();
  }

  addDefault(path: string): void {
    this.defaults.add(path);
  }

  removeDefault(path: string): void {
    this.defaults.remove(path);
  }

  listForTask(taskId: string): string[] {
    return this.workspaces.getAdditionalDirectories(taskId);
  }

  addForTask(taskId: string, path: string): void {
    this.workspaces.addAdditionalDirectory(taskId, path);
  }

  removeForTask(taskId: string, path: string): void {
    this.workspaces.removeAdditionalDirectory(taskId, path);
  }
}
