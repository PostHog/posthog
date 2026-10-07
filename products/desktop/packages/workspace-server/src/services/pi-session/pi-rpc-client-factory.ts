import { homedir } from "node:os";
import { join } from "node:path";
import {
  createLocalRuntimeMcpServers,
  createPiRpcClient,
  createRuntimeMcpServers,
  type PiRpcClient,
} from "@posthog/agent/pi/rpc-client";
import { getLlmGatewayUrl } from "@posthog/agent/posthog-api";
import { ROOT_LOGGER, type RootLogger } from "@posthog/di/logger";
import {
  type CloudRegion,
  getCloudUrlFromRegion,
  type McpServerConnection,
} from "@posthog/shared";
import { buildPosthogScopedPropertyHeaderRecord } from "@posthog/shared/posthog-property-headers";
import type { TaskContext } from "@posthog/shared/task-context";
import { inject, injectable } from "inversify";
import { prepareContextWiki } from "../agent/context-wiki";
import {
  AGENT_AUTH,
  AGENT_MCP_APPS,
  MCP_SERVER_CONNECTION_SOURCE,
} from "../agent/identifiers";
import type {
  AgentAuth,
  AgentMcpApps,
  McpServerConnectionSource,
} from "../agent/ports";
import type { AuthProxyService } from "../auth-proxy/auth-proxy";
import { resolveGatewayProxy } from "../auth-proxy/gateway-proxy";
import {
  AUTH_PROXY_SERVICE,
  GATEWAY_CREDENTIAL_SOURCE,
} from "../auth-proxy/identifiers";
import {
  type GatewayCredentialSource,
  AUTH_PROXY_PLACEHOLDER_CREDENTIAL as PROXY_API_KEY,
} from "../auth-proxy/ports";
import type { PiRpcClientFactory } from "./identifiers";

@injectable()
export class LocalPiRpcClientFactory implements PiRpcClientFactory {
  constructor(
    @inject(AGENT_AUTH) private readonly auth: AgentAuth,
    @inject(AUTH_PROXY_SERVICE)
    private readonly authProxy: AuthProxyService,
    @inject(MCP_SERVER_CONNECTION_SOURCE)
    private readonly mcpServerSource: McpServerConnectionSource,
    @inject(AGENT_MCP_APPS) private readonly mcpApps: AgentMcpApps,
    @inject(ROOT_LOGGER) private readonly rootLogger: RootLogger,
    // Required: an unbound source would silently keep Pi on legacy.
    @inject(GATEWAY_CREDENTIAL_SOURCE)
    private readonly gatewaySource: GatewayCredentialSource,
  ) {}

  async create(
    input: Parameters<PiRpcClientFactory["create"]>[0],
  ): Promise<PiRpcClient> {
    const credentials = await this.auth.getOAuthCredentials();
    if (!credentials) {
      throw new Error("Pi requires PostHog authentication");
    }

    const projectId = this.auth.getState().currentProjectId;
    if (!projectId) {
      throw new Error("Pi requires a selected PostHog project");
    }
    const access = await this.auth.getValidAccessToken();
    // Four independent round-trips: proxy URL, auth proxy, MCP config, wiki mount.
    const [baseUrl, enrichmentApiUrl, mcpConfiguration, contextWikiPath] =
      await Promise.all([
        this.getProxyUrl(
          credentials.region,
          projectId,
          input.taskContext.taskId,
        ),
        this.authProxy.start(access.apiHost),
        this.mcpServerSource.getMcpRuntimeConfiguration(),
        this.mountContextWiki(projectId),
      ]);
    const runtimeMcpServers = {
      ...createRuntimeMcpServers(mcpConfiguration.servers),
      ...createLocalRuntimeMcpServers(input.taskContext.cwd),
    };
    this.registerMcpAppsServers(mcpConfiguration.servers);
    const taskContext: TaskContext = {
      projectId,
      apiHost: access.apiHost,
      environment: "local",
      ...input.taskContext,
    };

    return createPiRpcClient({
      model: input.model,
      sessionFile: input.sessionFile,
      taskContext,
      enrichment: {
        apiUrl: enrichmentApiUrl,
        publicApiUrl: access.apiHost,
        projectId,
        apiKey: PROXY_API_KEY,
      },
      runtimeMcpServers,
      mcpToolPolicies: mcpConfiguration.policies,
      providerOptions: {
        region: credentials.region,
        baseUrl,
        apiKey: PROXY_API_KEY,
        claudeOAuthToken: input.claudeOAuthToken,
      },
      extensions: ["context-wiki"],
      contextWikiPath,
    });
  }

  private registerMcpAppsServers(servers: McpServerConnection[]): void {
    this.mcpApps.addServerConfigs(
      servers.map((server) => ({
        name: server.name,
        url: server.url,
        headers: Object.fromEntries(
          (server.headers ?? []).map((header) => [header.name, header.value]),
        ),
      })),
    );
    this.mcpApps
      .handleDiscovery(servers.map((server) => server.name))
      .catch((err) => {
        this.rootLogger
          .scope("pi-mcp-apps")
          .warn("MCP Apps discovery failed for a Pi session", {
            error: err instanceof Error ? err.message : String(err),
          });
      });
  }

  /**
   * Pi sessions don't go through AgentService, so they mount the org's
   * context wiki themselves. Best-effort: the session starts without a wiki
   * on any failure.
   */
  private async mountContextWiki(
    projectId: number,
  ): Promise<string | undefined> {
    try {
      const { apiHost } = await this.auth.getValidAccessToken();
      const mount = await prepareContextWiki({
        apiHost,
        projectId,
        authenticatedFetch: (input, init) =>
          this.auth.authenticatedFetch(fetch, input, init),
        cacheDir: join(homedir(), ".posthog-code", "context-wiki"),
        log: this.rootLogger.scope("pi-context-wiki"),
      });
      return mount?.path;
    } catch (err) {
      this.rootLogger
        .scope("pi-context-wiki")
        .warn("Failed to mount the context wiki", {
          error: err instanceof Error ? err.message : String(err),
        });
      return undefined;
    }
  }

  private async getProxyUrl(
    region: CloudRegion,
    projectId: number,
    taskId: string,
  ): Promise<string> {
    const { proxyUrl } = await resolveGatewayProxy({
      authProxy: this.authProxy,
      source: this.gatewaySource,
      legacyGatewayUrl: getLlmGatewayUrl(getCloudUrlFromRegion(region)),
      projectId,
      headers: buildPosthogScopedPropertyHeaderRecord(
        { task_id: taskId, $ai_session_id: taskId },
        projectId,
      ),
    });
    return proxyUrl;
  }
}
