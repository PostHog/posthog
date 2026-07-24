export interface ShellCreateInput {
  sessionId: string;
  cwd?: string;
  taskId?: string;
}

export interface ShellCreateCommandInput {
  sessionId: string;
  command: string;
  cwd: string;
  taskId?: string;
}

export interface ShellResizeInput {
  sessionId: string;
  cols: number;
  rows: number;
}

export interface ShellClient {
  write(input: { sessionId: string; data: string }): Promise<void>;
  check(input: { sessionId: string }): Promise<boolean>;
  destroy(input: { sessionId: string }): Promise<void>;
  create(input: ShellCreateInput): Promise<void>;
  createCommand(input: ShellCreateCommandInput): Promise<void>;
  resize(input: ShellResizeInput): Promise<void>;
  getProcess(input: { sessionId: string }): Promise<string | null>;
  execute(input: {
    cwd: string;
    command: string;
  }): Promise<{ stdout: string; stderr: string; exitCode: number }>;
  openExternal(input: { url: string }): Promise<void>;
  onData(
    sessionId: string,
    onEvent: (event: { sessionId: string; data: string }) => void,
  ): { unsubscribe: () => void };
  onExit(
    sessionId: string,
    onEvent: (event: { sessionId: string; exitCode: number | null }) => void,
  ): { unsubscribe: () => void };
}

export const SHELL_CLIENT = Symbol.for("posthog.ui.ShellClient");
