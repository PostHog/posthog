import {
  type McpToolApprovalState,
  type McpToolApprovals,
  sanitizeMcpServerName,
} from "@posthog/agent/adapters/claude/mcp/tool-metadata";
import { getLlmGatewayUrl } from "@posthog/agent/posthog-api";
import { inject, injectable } from "inversify";
import type { AuthProxyService } from "../auth-proxy/auth-proxy";
import { AUTH_PROXY_SERVICE } from "../auth-proxy/identifiers";
import { MCP_PROXY_SERVICE } from "../mcp-proxy/identifiers";
import type { McpProxyService } from "../mcp-proxy/mcp-proxy";
import { AGENT_AUTH, AGENT_LOGGER } from "./identifiers";
import type { AgentAuth, AgentLogger, AgentScopedLogger } from "./ports";
import type { Credentials } from "./schemas";

const VALID_APPROVAL_STATES = new Set([
  "approved",
  "needs_approval",
  "do_not_use",
]);
function isValidApprovalState(value: string): value is McpToolApprovalState {
  return VALID_APPROVAL_STATES.has(value);
}

export interface AcpMcpServer {
  name: string;
  type: "http";
  url: string;
  headers: Array<{ name: string; value: string }>;
}

export interface AgentPosthogConfig {
  apiUrl: string;
  getApiKey: () => Promise<string>;
  refreshApiKey: () => Promise<string>;
  projectId: number;
}

/** Reference linking an MCP tool key back to its server installation for backend updates. */
export interface McpToolInstallationRef {
  installationId: string;
  toolName: string;
}

/** Maps MCP tool keys (e.g. `mcp__server__tool`) to their installation reference. */
export type McpToolInstallations = Record<string, McpToolInstallationRef>;

interface ConfigureProcessEnvInput {
  credentials: Credentials;
  proxyUrl: string;
  claudeCliPath: string;
  /** rtk command-output compression for the session; false opts out. */
  rtkEnabled?: boolean;
}

@injectable()
export class AgentAuthAdapter {
  private readonly log: AgentScopedLogger;

  constructor(
    @inject(AGENT_AUTH)
    private readonly authService: AgentAuth,
    @inject(AUTH_PROXY_SERVICE)
    private readonly authProxy: AuthProxyService,
    @inject(MCP_PROXY_SERVICE)
    private readonly mcpProxy: McpProxyService,
    @inject(AGENT_LOGGER)
    loggerFactory: AgentLogger,
  ) {
    this.log = loggerFactory.scope("agent-auth-adapter");
  }

  createPosthogConfig(credentials: Credentials): AgentPosthogConfig {
    return {
      apiUrl: credentials.apiHost,
      getApiKey: () => this.getValidToken(),
      refreshApiKey: () => this.refreshToken(),
      projectId: credentials.projectId,
    };
  }

  /**
   * The current signed-in credentials from auth state, or null when no project is
   * selected. Lets the mcp-apps config resolver register servers for a cloud run
   * without a session (where the renderer never supplies credentials).
   */
  async getCurrentCredentials(): Promise<Credentials | null> {
    const { apiHost } = await this.authService.getValidAccessToken();
    const projectId = this.authService.getState().currentProjectId;
    return projectId === null ? null : { apiHost, projectId };
  }

  async buildMcpServers(credentials: Credentials): Promise<{
    servers: AcpMcpServer[];
    toolApprovals: McpToolApprovals;
    toolInstallations: McpToolInstallations;
  }> {
    const servers: AcpMcpServer[] = [];
    const mcpUrl = this.getPostHogMcpUrl(credentials.apiHost);
    // Warm the token so authenticatedFetch() has something cached, but do not
    // bake it into the MCP config — the proxy injects a fresh one on every
    // forwarded request.
    await this.getValidToken();

    await this.mcpProxy.start();
    const proxiedPosthogUrl = this.mcpProxy.register("posthog", mcpUrl);

    servers.push({
      name: "posthog",
      type: "http",
      url: proxiedPosthogUrl,
      headers: [
        {
          name: "x-posthog-project-id",
          value: String(credentials.projectId),
        },
        { name: "x-posthog-mcp-version", value: "2" },
        { name: "x-posthog-mcp-consumer", value: "posthog-code" },
      ],
    });

    const installations = await this.fetchMcpInstallations(credentials);

    for (const installation of installations) {
      if (installation.url === mcpUrl) continue;

      const name =
        installation.name || installation.display_name || installation.url;

      const proxiedUrl = this.mcpProxy.register(
        `installation-${installation.id}`,
        installation.proxy_url,
      );
      servers.push({
        name,
        type: "http",
        url: proxiedUrl,
        headers: [],
      });
    }

    const { approvals: toolApprovals, toolInstallations } =
      await this.fetchMcpToolApprovals(credentials, installations);

    return { servers, toolApprovals, toolInstallations };
  }

  async ensureGatewayProxy(apiHost: string): Promise<string> {
    return this.authProxy.start(getLlmGatewayUrl(apiHost));
  }

  /**
   * Bearer token for direct gateway REST calls (the models fetch), so the
   * gateway can mark plan-restricted models. Null when auth isn't available —
   * callers fall back to an anonymous fetch.
   */
  async gatewayAuthToken(): Promise<string | null> {
    try {
      return await this.getValidToken();
    } catch {
      return null;
    }
  }

  async configureProcessEnv({
    credentials,
    proxyUrl,
    claudeCliPath,
    rtkEnabled,
  }: ConfigureProcessEnvInput): Promise<void> {
    await this.getValidToken();

    process.env.LLM_GATEWAY_URL = proxyUrl;
    process.env.CLAUDE_CODE_EXECUTABLE = claudeCliPath;
    process.env.POSTHOG_API_URL = credentials.apiHost;
    process.env.POSTHOG_PROJECT_ID = String(credentials.projectId);
    // The agent auto-detects rtk on PATH; an explicit opt-out from settings
    // pins it off for sessions this process spawns. Deleting on the enabled
    // path restores auto-detection after a re-enable without a restart.
    if (rtkEnabled === false) {
      process.env.POSTHOG_RTK = "0";
    } else {
      delete process.env.POSTHOG_RTK;
    }
  }

  private syncTokenEnvironment(token: string): void {
    process.env.POSTHOG_API_KEY = token;
    process.env.POSTHOG_AUTH_HEADER = `Bearer ${token}`;
  }

  private async getValidToken(): Promise<string> {
    const { accessToken } = await this.authService.getValidAccessToken();
    this.syncTokenEnvironment(accessToken);
    return accessToken;
  }

  private async refreshToken(): Promise<string> {
    const { accessToken } = await this.authService.refreshAccessToken();
    this.syncTokenEnvironment(accessToken);
    return accessToken;
  }

  private getPostHogMcpUrl(apiHost: string): string {
    const overrideUrl = process.env.POSTHOG_MCP_URL;
    if (overrideUrl) {
      return overrideUrl;
    }
    if (apiHost.includes("localhost") || apiHost.includes("127.0.0.1")) {
      return "http://localhost:8787/mcp";
    }
    return "https://mcp.posthog.com/mcp";
  }

  private getPostHogApiBaseUrl(apiHost: string): string {
    const host = process.env.POSTHOG_PROXY_BASE_URL || apiHost;
    return host.endsWith("/") ? host.slice(0, -1) : host;
  }

  async updateMcpToolApproval(
    credentials: Credentials,
    installationId: string,
    toolName: string,
    approvalState: McpToolApprovalState,
  ): Promise<void> {
    const baseUrl = this.getPostHogApiBaseUrl(credentials.apiHost);
    const url = `${baseUrl}/api/environments/${credentials.projectId}/mcp_server_installations/${installationId}/tools/${encodeURIComponent(toolName)}/`;
    const response = await this.authService.authenticatedFetch(fetch, url, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ approval_state: approvalState }),
    });
    if (!response.ok) {
      throw new Error(
        `Failed to update MCP tool approval (${response.status}) for ${toolName} on installation ${installationId}`,
      );
    }
  }

  private async fetchMcpToolApprovals(
    credentials: Credentials,
    installations: Array<{
      id: string;
      url: string;
      name: string;
      display_name: string;
    }>,
  ): Promise<{
    approvals: McpToolApprovals;
    toolInstallations: McpToolInstallations;
  }> {
    const baseUrl = this.getPostHogApiBaseUrl(credentials.apiHost);
    const approvals: McpToolApprovals = {};
    const toolInstallations: McpToolInstallations = {};

    const results = await Promise.allSettled(
      installations.map(async (installation) => {
        const serverName = sanitizeMcpServerName(
          installation.name || installation.display_name || installation.url,
        );
        const toolsUrl = `${baseUrl}/api/environments/${credentials.projectId}/mcp_server_installations/${installation.id}/tools/`;

        const response = await this.authService.authenticatedFetch(
          fetch,
          toolsUrl,
          { headers: { "Content-Type": "application/json" } },
        );
        if (!response.ok) return [];

        const data = (await response.json()) as {
          results?: Array<{
            tool_name: string;
            approval_state?: string;
          }>;
        };
        return (data.results ?? []).map((tool) => ({
          serverName,
          installationId: installation.id,
          toolName: tool.tool_name,
          approvalState: tool.approval_state,
        }));
      }),
    );

    for (const result of results) {
      if (result.status !== "fulfilled") {
        this.log.warn("Failed to fetch tool approvals for an installation", {
          error:
            result.reason instanceof Error
              ? result.reason.message
              : String(result.reason),
        });
        continue;
      }
      for (const tool of result.value) {
        const key = `mcp__${tool.serverName}__${tool.toolName}`;
        if (tool.approvalState && isValidApprovalState(tool.approvalState)) {
          approvals[key] = tool.approvalState;
        }
        toolInstallations[key] = {
          installationId: tool.installationId,
          toolName: tool.toolName,
        };
      }
    }

    return { approvals, toolInstallations };
  }

  private async fetchMcpInstallations(credentials: Credentials): Promise<
    Array<{
      id: string;
      url: string;
      proxy_url: string;
      name: string;
      display_name: string;
      auth_type: string;
    }>
  > {
    const baseUrl = this.getPostHogApiBaseUrl(credentials.apiHost);
    const url = `${baseUrl}/api/environments/${credentials.projectId}/mcp_server_installations/`;

    try {
      const response = await this.authService.authenticatedFetch(fetch, url, {
        headers: {
          "Content-Type": "application/json",
        },
      });

      if (!response.ok) {
        this.log.warn("Failed to fetch MCP installations", {
          status: response.status,
        });
        return [];
      }

      const data = (await response.json()) as {
        results?: Array<{
          id: string;
          url: string;
          proxy_url?: string;
          name: string;
          display_name: string;
          auth_type: string;
          is_enabled?: boolean;
          pending_oauth: boolean;
          needs_reauth: boolean;
        }>;
      };
      const installations = data.results ?? [];

      return installations
        .filter(
          (i) => !i.pending_oauth && !i.needs_reauth && i.is_enabled !== false,
        )
        .map((i) => ({
          ...i,
          proxy_url:
            i.proxy_url ??
            `${baseUrl}/api/environments/${credentials.projectId}/mcp_server_installations/${i.id}/proxy/`,
        }));
    } catch (err) {
      this.log.warn("Error fetching MCP installations", { error: err });
      return [];
    }
  }
}
