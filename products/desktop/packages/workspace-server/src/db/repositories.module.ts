import { ContainerModule } from "inversify";
import {
  ARCHIVE_REPOSITORY,
  AUTH_PREFERENCE_REPOSITORY,
  AUTH_SESSION_REPOSITORY,
  AUTORESEARCH_RUN_REPOSITORY,
  BROWSER_TABS_REPOSITORY,
  CLAUDE_SESSION_IMPORT_REPOSITORY,
  DEFAULT_ADDITIONAL_DIRECTORY_REPOSITORY,
  REPOSITORY_REPOSITORY,
  SUSPENSION_REPOSITORY,
  TASK_METADATA_REPOSITORY,
  WORKSPACE_REPOSITORY,
  WORKTREE_REPOSITORY,
} from "./identifiers";
import { ArchiveRepository } from "./repositories/archive-repository";
import { AuthPreferenceRepository } from "./repositories/auth-preference-repository";
import { AuthSessionRepository } from "./repositories/auth-session-repository";
import { AutoresearchRunRepository } from "./repositories/autoresearch-run-repository";
import { BrowserTabsRepository } from "./repositories/browser-tabs-repository";
import { ClaudeSessionImportRepository } from "./repositories/claude-session-import-repository";
import { DefaultAdditionalDirectoryRepository } from "./repositories/default-additional-directory-repository";
import { RepositoryRepository } from "./repositories/repository-repository";
import { SuspensionRepositoryImpl } from "./repositories/suspension-repository";
import { TaskMetadataRepository } from "./repositories/task-metadata-repository";
import { WorkspaceRepository } from "./repositories/workspace-repository";
import { WorktreeRepository } from "./repositories/worktree-repository";

export const repositoriesModule = new ContainerModule(({ bind }) => {
  bind(REPOSITORY_REPOSITORY).to(RepositoryRepository).inSingletonScope();
  bind(WORKSPACE_REPOSITORY).to(WorkspaceRepository).inSingletonScope();
  bind(WORKTREE_REPOSITORY).to(WorktreeRepository).inSingletonScope();
  bind(ARCHIVE_REPOSITORY).to(ArchiveRepository).inSingletonScope();
  bind(SUSPENSION_REPOSITORY).to(SuspensionRepositoryImpl).inSingletonScope();
  bind(AUTH_SESSION_REPOSITORY).to(AuthSessionRepository).inSingletonScope();
  bind(AUTH_PREFERENCE_REPOSITORY)
    .to(AuthPreferenceRepository)
    .inSingletonScope();
  bind(DEFAULT_ADDITIONAL_DIRECTORY_REPOSITORY)
    .to(DefaultAdditionalDirectoryRepository)
    .inSingletonScope();
  bind(TASK_METADATA_REPOSITORY).to(TaskMetadataRepository).inSingletonScope();
  bind(AUTORESEARCH_RUN_REPOSITORY)
    .to(AutoresearchRunRepository)
    .inSingletonScope();
  bind(CLAUDE_SESSION_IMPORT_REPOSITORY)
    .to(ClaudeSessionImportRepository)
    .inSingletonScope();
  bind(BROWSER_TABS_REPOSITORY).to(BrowserTabsRepository).inSingletonScope();
});
