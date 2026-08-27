import { exec } from "node:child_process";
import { existsSync } from "node:fs";
import { homedir, platform } from "node:os";
import {
  ROOT_LOGGER,
  type RootLogger,
  type ScopedLogger,
} from "@posthog/di/logger";
import {
  type IWorkspaceSettings,
  WORKSPACE_SETTINGS_SERVICE,
} from "@posthog/platform/workspace-settings";
import { TypedEventEmitter } from "@posthog/shared";
import { POSTHOG_CODE_INTERNAL_CHILD_ENV } from "@posthog/shared/constants";
import { inject, injectable, preDestroy } from "inversify";
import * as pty from "node-pty";
import {
  REPOSITORY_REPOSITORY,
  WORKSPACE_REPOSITORY,
  WORKTREE_REPOSITORY,
} from "../../db/identifiers";
import type { RepositoryRepository } from "../../db/repositories/repository-repository";
import type { WorkspaceRepository } from "../../db/repositories/workspace-repository";
import type { WorktreeRepository } from "../../db/repositories/worktree-repository";
import { buildWorkspaceEnv } from "../../workspace-env";
import { PROCESS_TRACKING_SERVICE } from "../process-tracking/identifiers";
import type { ProcessTrackingService } from "../process-tracking/process-tracking";
import { deriveWorktreePath as deriveWorktreePathFromBase } from "../worktree-path/worktree-path";
import { type ExecuteOutput, ShellEvent, type ShellEvents } from "./schemas";

// node-pty exposes destroy() at runtime but it's missing from type definitions
declare module "node-pty" {
  interface IPty {
    destroy(): void;
  }
}

const PTY_ENCODING = "utf8";
const DESTROYED_EXIT_CODE = 130;

export interface ShellSession {
  pty: pty.IPty;
  exitPromise: Promise<{ exitCode: number }>;
  command?: string;
  disposables: pty.IDisposable[];
}

function getDefaultShell(): string {
  if (platform() === "win32") {
    return process.env.COMSPEC || "cmd.exe";
  }
  return process.env.SHELL || "/bin/bash";
}

function getShellArgs(shell: string): string[] {
  if (platform() === "win32") {
    const lower = shell.toLowerCase();
    if (lower.includes("powershell") || lower.includes("pwsh")) {
      return ["-NoLogo"];
    }
    return [];
  }
  return ["-l"];
}

function buildShellEnv(
  additionalEnv?: Record<string, string>,
): Record<string, string> {
  const env = { ...process.env } as Record<string, string>;

  // User-facing shells must not inherit the workspace-server's internal
  // markers: ELECTRON_RUN_AS_NODE makes any Electron-based CLI run as node,
  // and the internal-child marker makes the packaged app refuse to launch.
  delete env.ELECTRON_RUN_AS_NODE;
  delete env[POSTHOG_CODE_INTERNAL_CHILD_ENV];

  if (platform() === "darwin" && !process.env.LC_ALL) {
    const locale = process.env.LC_CTYPE || "en_US.UTF-8";
    Object.assign(env, {
      LANG: locale,
      LC_ALL: locale,
      LC_MESSAGES: locale,
      LC_NUMERIC: locale,
      LC_COLLATE: locale,
      LC_MONETARY: locale,
    });
  }

  Object.assign(env, {
    TERM_PROGRAM: "PostHog",
    COLORTERM: "truecolor",
    FORCE_COLOR: "3",
    ...additionalEnv,
  });

  return env;
}

export interface CreateSessionOptions {
  sessionId: string;
  cwd?: string;
  taskId?: string;
  initialCommand?: string;
  additionalEnv?: Record<string, string>;
}

@injectable()
export class ShellService extends TypedEventEmitter<ShellEvents> {
  private sessions = new Map<string, ShellSession>();
  private processTracking: ProcessTrackingService;
  private repositoryRepo: RepositoryRepository;
  private workspaceRepo: WorkspaceRepository;
  private worktreeRepo: WorktreeRepository;
  private readonly log: ScopedLogger;

  constructor(
    @inject(PROCESS_TRACKING_SERVICE)
    processTracking: ProcessTrackingService,
    @inject(REPOSITORY_REPOSITORY)
    repositoryRepo: RepositoryRepository,
    @inject(WORKSPACE_REPOSITORY)
    workspaceRepo: WorkspaceRepository,
    @inject(WORKTREE_REPOSITORY)
    worktreeRepo: WorktreeRepository,
    @inject(WORKSPACE_SETTINGS_SERVICE)
    private readonly workspaceSettings: IWorkspaceSettings,
    @inject(ROOT_LOGGER)
    logger: RootLogger,
  ) {
    super();
    this.processTracking = processTracking;
    this.repositoryRepo = repositoryRepo;
    this.workspaceRepo = workspaceRepo;
    this.worktreeRepo = worktreeRepo;
    this.log = logger.scope("shell");
  }

  private deriveWorktreePath(folderPath: string, worktreeName: string): string {
    return deriveWorktreePathFromBase(
      this.workspaceSettings.getWorktreeLocation(),
      folderPath,
      worktreeName,
    );
  }

  async create(
    sessionId: string,
    cwd?: string,
    taskId?: string,
  ): Promise<void> {
    await this.createSession({ sessionId, cwd, taskId });
  }

  async createSession(options: CreateSessionOptions): Promise<ShellSession> {
    const { sessionId, cwd, taskId, initialCommand, additionalEnv } = options;

    const existing = this.sessions.get(sessionId);
    if (existing) {
      return existing;
    }

    const taskEnv = await this.getTaskEnv(taskId);
    const mergedEnv = { ...taskEnv, ...additionalEnv };
    const workingDir = this.resolveWorkingDir(sessionId, cwd);
    const shell = getDefaultShell();

    const ptyProcess = pty.spawn(shell, getShellArgs(shell), {
      name: "xterm-256color",
      cols: 80,
      rows: 24,
      cwd: workingDir,
      env: buildShellEnv(mergedEnv),
      encoding: PTY_ENCODING,
    });

    this.processTracking.register(
      ptyProcess.pid,
      "shell",
      `shell:${sessionId}`,
      { sessionId, cwd: workingDir },
      taskId,
    );

    let resolveExit: (result: { exitCode: number }) => void;
    const exitPromise = new Promise<{ exitCode: number }>((resolve) => {
      resolveExit = resolve;
    });

    const disposables: pty.IDisposable[] = [];

    disposables.push(
      ptyProcess.onData((data: string) => {
        this.emit(ShellEvent.Data, { sessionId, data });
      }),
    );

    disposables.push(
      ptyProcess.onExit(({ exitCode }) => {
        this.processTracking.unregister(ptyProcess.pid, "exited");
        const session = this.sessions.get(sessionId);
        if (session) {
          for (const d of session.disposables) {
            d.dispose();
          }
          session.pty.destroy();
          this.sessions.delete(sessionId);
        }
        this.emit(ShellEvent.Exit, { sessionId, exitCode });
        resolveExit({ exitCode });
      }),
    );

    if (initialCommand) {
      setTimeout(() => {
        ptyProcess.write(`${initialCommand}\n`);
      }, 100);
    }

    const session: ShellSession = {
      pty: ptyProcess,
      exitPromise,
      command: initialCommand,
      disposables,
    };

    this.sessions.set(sessionId, session);
    return session;
  }

  async createCommandSession(options: {
    sessionId: string;
    command: string;
    cwd: string;
    taskId?: string;
  }): Promise<void> {
    const { sessionId, command, cwd, taskId } = options;

    const existing = this.sessions.get(sessionId);
    if (existing) {
      return;
    }

    const taskEnv = await this.getTaskEnv(taskId);
    const workingDir = this.resolveWorkingDir(sessionId, cwd);
    const shell = getDefaultShell();

    const ptyProcess = pty.spawn(shell, ["-c", command], {
      name: "xterm-256color",
      cols: 80,
      rows: 24,
      cwd: workingDir,
      env: buildShellEnv(taskEnv),
      encoding: PTY_ENCODING,
    });

    this.processTracking.register(
      ptyProcess.pid,
      "shell",
      `shell:${sessionId}`,
      { sessionId, cwd: workingDir, command },
      taskId,
    );

    let resolveExit: (result: { exitCode: number }) => void;
    const exitPromise = new Promise<{ exitCode: number }>((resolve) => {
      resolveExit = resolve;
    });

    const disposables: pty.IDisposable[] = [];

    disposables.push(
      ptyProcess.onData((data: string) => {
        this.emit(ShellEvent.Data, { sessionId, data });
      }),
    );

    disposables.push(
      ptyProcess.onExit(({ exitCode }) => {
        this.processTracking.unregister(ptyProcess.pid, "exited");
        const session = this.sessions.get(sessionId);
        if (session) {
          for (const d of session.disposables) {
            d.dispose();
          }
          session.pty.destroy();
          this.sessions.delete(sessionId);
        }
        this.emit(ShellEvent.Exit, { sessionId, exitCode });
        resolveExit({ exitCode });
      }),
    );

    const session: ShellSession = {
      pty: ptyProcess,
      exitPromise,
      command,
      disposables,
    };

    this.sessions.set(sessionId, session);
  }

  write(sessionId: string, data: string): void {
    this.getSessionOrThrow(sessionId).pty.write(data);
  }

  resize(sessionId: string, cols: number, rows: number): void {
    this.getSessionOrThrow(sessionId).pty.resize(cols, rows);
  }

  check(sessionId: string): boolean {
    return this.sessions.has(sessionId);
  }

  hasSession(sessionId: string): boolean {
    return this.sessions.has(sessionId);
  }

  getSession(sessionId: string): ShellSession | undefined {
    return this.sessions.get(sessionId);
  }

  getSessionsByPrefix(prefix: string): string[] {
    const result: string[] = [];
    for (const sessionId of this.sessions.keys()) {
      if (sessionId.startsWith(prefix)) {
        result.push(sessionId);
      }
    }
    return result;
  }

  destroyByPrefix(prefix: string): void {
    for (const sessionId of this.sessions.keys()) {
      if (sessionId.startsWith(prefix)) {
        this.destroy(sessionId);
      }
    }
  }

  destroy(sessionId: string): void {
    const session = this.sessions.get(sessionId);
    if (session) {
      const pid = session.pty.pid;
      this.processTracking.kill(pid);
      for (const disposable of session.disposables) {
        disposable.dispose();
      }
      session.pty.destroy();
      this.sessions.delete(sessionId);
      this.emit(ShellEvent.Exit, {
        sessionId,
        exitCode: DESTROYED_EXIT_CODE,
      });
    }
  }

  /**
   * Destroy all active shell sessions.
   * Used during application shutdown to ensure all child processes are cleaned up.
   */
  @preDestroy()
  destroyAll(): void {
    for (const sessionId of this.sessions.keys()) {
      this.destroy(sessionId);
    }
  }

  /**
   * Get the count of active sessions.
   */
  getSessionCount(): number {
    return this.sessions.size;
  }

  getProcess(sessionId: string): string | null {
    return this.sessions.get(sessionId)?.pty.process ?? null;
  }

  execute(cwd: string, command: string): Promise<ExecuteOutput> {
    return new Promise((resolve) => {
      exec(
        command,
        { cwd, timeout: 60000, env: buildShellEnv() },
        (error, stdout, stderr) => {
          resolve({
            stdout: stdout || "",
            stderr: stderr || "",
            exitCode: error?.code ?? 0,
          });
        },
      );
    });
  }

  private getSessionOrThrow(sessionId: string): ShellSession {
    const session = this.sessions.get(sessionId);
    if (!session) {
      throw new Error(`Shell session ${sessionId} not found`);
    }
    return session;
  }

  private resolveWorkingDir(sessionId: string, cwd?: string): string {
    const home = homedir();
    const workingDir = cwd || home;

    if (!existsSync(workingDir)) {
      this.log.warn(
        `Shell session ${sessionId}: cwd "${workingDir}" does not exist, falling back to home`,
      );
      return home;
    }

    return workingDir;
  }

  private async getTaskEnv(
    taskId?: string,
  ): Promise<Record<string, string> | undefined> {
    if (!taskId) return undefined;

    const workspace = this.workspaceRepo.findByTaskId(taskId);
    if (!workspace || workspace.mode === "cloud" || !workspace.repositoryId) {
      return undefined;
    }

    const repo = this.repositoryRepo.findById(workspace.repositoryId);
    if (!repo) return undefined;

    let worktreePath: string | null = null;
    let worktreeName: string | null = null;

    if (workspace.mode === "worktree") {
      const worktree = this.worktreeRepo.findByWorkspaceId(workspace.id);
      if (worktree) {
        worktreeName = worktree.name;
        // The stored path is authoritative — reused worktrees can live
        // outside the managed worktree directory. Only derive when the
        // stored path is gone (e.g. stale row after a location move).
        worktreePath = existsSync(worktree.path)
          ? worktree.path
          : this.deriveWorktreePath(repo.path, worktreeName);
      }
    }

    try {
      return await buildWorkspaceEnv({
        taskId,
        folderPath: repo.path,
        worktreePath,
        worktreeName,
        mode: workspace.mode,
      });
    } catch (error) {
      this.log.warn(
        `Failed to build workspace env for task ${taskId}, starting shell without it`,
        error,
      );
      return undefined;
    }
  }
}
