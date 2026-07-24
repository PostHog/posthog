import type { CloudRegion } from "@posthog/shared";

// Narrow ports inverting AgentService's dependencies on core/host services so it
// can live in workspace-server without importing @posthog/core or apps/code.
// The host (apps/code) binds these to the concrete SleepService, McpAppsService,
// FsService bridge, AuthService, and scoped logger.

export interface AgentScopedLogger {
  debug(message: string, ...args: unknown[]): void;
  info(message: string, ...args: unknown[]): void;
  warn(message: string, ...args: unknown[]): void;
  error(message: string, ...args: unknown[]): void;
}

export interface AgentLogger {
  scope(scope: string): AgentScopedLogger;
}

export interface AgentSleepCoordinator {
  acquire(activityId: string): void;
  release(activityId: string): void;
}

export interface AgentMcpServerConnectionConfig {
  name: string;
  url: string;
  headers: Record<string, string>;
}

export interface AgentMcpApps {
  handleDiscovery(serverNames: string[]): Promise<void>;
  setServerConfigs(configs: AgentMcpServerConnectionConfig[]): void;
  addServerConfigs(configs: AgentMcpServerConnectionConfig[]): void;
  setConfigResolver(resolver: (serverName: string) => Promise<void>): void;
  notifyToolCancelled(toolKey: string, toolCallId: string): void;
  notifyToolInput(toolKey: string, toolCallId: string, args: unknown): void;
  notifyToolResult(
    toolKey: string,
    toolCallId: string,
    result: unknown,
    isError?: boolean,
  ): void;
  cleanup(): Promise<void>;
}

export interface AgentRepoFiles {
  readRepoFile(repoPath: string, filePath: string): Promise<string | null>;
  writeRepoFile(
    repoPath: string,
    filePath: string,
    content: string,
  ): Promise<void>;
}

type AgentFetchLike = (
  input: string | Request,
  init?: RequestInit,
) => Promise<Response>;

export interface AgentAuth {
  getValidAccessToken(): Promise<{ accessToken: string; apiHost: string }>;
  getOAuthCredentials(): Promise<{
    access: string;
    refresh: string;
    expires: number;
    region: CloudRegion;
  } | null>;
  refreshAccessToken(): Promise<{ accessToken: string; apiHost: string }>;
  getState(): { currentProjectId: number | null };
  authenticatedFetch(
    fetchImpl: AgentFetchLike,
    input: string | Request,
    init?: RequestInit,
  ): Promise<Response>;
}
