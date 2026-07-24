import "reflect-metadata";
import { TypedContainer } from "@inversifyjs/strongly-typed";
import { ConnectivityService } from "../services/connectivity/service";
import { EnvironmentService } from "../services/environment/service";
import { FocusService } from "../services/focus/service";
import { FocusSyncService } from "../services/focus/sync-service";
import { FsService } from "../services/fs/service";
import { GitService } from "../services/git/service";
import { LOGS_SERVICE } from "../services/local-logs/identifiers";
import { LocalLogsService } from "../services/local-logs/service";
import { WatcherService } from "../services/watcher/service";
import {
  CONNECTIVITY_SERVICE,
  ENVIRONMENT_SERVICE,
  FOCUS_SERVICE,
  FOCUS_SYNC_SERVICE,
  FS_SERVICE,
  GIT_SERVICE,
  LOCAL_LOGS_SERVICE,
  WATCHER_SERVICE,
} from "./tokens";

export interface WorkspaceServerBindings {
  [FOCUS_SERVICE]: FocusService;
  [FOCUS_SYNC_SERVICE]: FocusSyncService;
  [GIT_SERVICE]: GitService;
  [FS_SERVICE]: FsService;
  [WATCHER_SERVICE]: WatcherService;
  [LOCAL_LOGS_SERVICE]: LocalLogsService;
  [LOGS_SERVICE]: LocalLogsService;
  [CONNECTIVITY_SERVICE]: ConnectivityService;
  [ENVIRONMENT_SERVICE]: EnvironmentService;
}

export const container = new TypedContainer<WorkspaceServerBindings>();
container.bind(FOCUS_SERVICE).to(FocusService).inSingletonScope();
container.bind(FOCUS_SYNC_SERVICE).to(FocusSyncService).inSingletonScope();
container.bind(GIT_SERVICE).to(GitService).inSingletonScope();
container.bind(FS_SERVICE).to(FsService).inSingletonScope();
container.bind(WATCHER_SERVICE).to(WatcherService).inSingletonScope();
container.bind(LOCAL_LOGS_SERVICE).to(LocalLogsService).inSingletonScope();
container.bind(LOGS_SERVICE).toService(LOCAL_LOGS_SERVICE);
container.bind(CONNECTIVITY_SERVICE).to(ConnectivityService).inSingletonScope();
container.bind(ENVIRONMENT_SERVICE).to(EnvironmentService).inSingletonScope();
