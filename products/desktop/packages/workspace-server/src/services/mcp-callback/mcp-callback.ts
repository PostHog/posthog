import {
  ROOT_LOGGER,
  type RootLogger,
  type ScopedLogger,
} from "@posthog/di/logger";
import { APP_META_SERVICE, type IAppMeta } from "@posthog/platform/app-meta";
import {
  DEEP_LINK_SERVICE,
  type IDeepLinkRegistry,
} from "@posthog/platform/deep-link";
import {
  type IUrlLauncher,
  URL_LAUNCHER_SERVICE,
} from "@posthog/platform/url-launcher";
import { TypedEventEmitter } from "@posthog/shared";
import { inject, injectable } from "inversify";
import { MCP_CALLBACK_SERVER } from "./identifiers";
import type { McpCallbackServer } from "./mcp-callback-server";
import {
  type GetCallbackUrlOutput,
  McpCallbackEvent,
  type McpCallbackEvents,
  type McpCallbackResult,
  type OpenAndWaitOutput,
} from "./schemas";

const MCP_CALLBACK_KEY = "mcp-oauth-complete";
const DEV_CALLBACK_PORT = 8238;
const OAUTH_TIMEOUT_MS = 180_000; // 3 minutes

interface PendingCallback {
  resolve: (result: McpCallbackResult) => void;
  reject: (error: Error) => void;
  timeoutId?: NodeJS.Timeout;
  abortController?: AbortController;
}

@injectable()
export class McpCallbackService extends TypedEventEmitter<McpCallbackEvents> {
  private pendingCallback: PendingCallback | null = null;
  private readonly log: ScopedLogger;

  constructor(
    @inject(DEEP_LINK_SERVICE)
    private readonly deepLinkService: IDeepLinkRegistry,
    @inject(URL_LAUNCHER_SERVICE)
    private readonly urlLauncher: IUrlLauncher,
    @inject(MCP_CALLBACK_SERVER)
    private readonly callbackServer: McpCallbackServer,
    @inject(APP_META_SERVICE)
    private readonly appMeta: IAppMeta,
    @inject(ROOT_LOGGER)
    logger: RootLogger,
  ) {
    super();
    this.log = logger.scope("mcp-callback");
    // Register deep link handler for MCP OAuth callbacks (production)
    this.deepLinkService.registerHandler(
      MCP_CALLBACK_KEY,
      (_path, searchParams) => this.handleCallback(searchParams),
    );
    this.log.info("Registered MCP OAuth callback handler for deep links");
  }

  /**
   * Get the callback URL based on environment (dev vs prod).
   */
  public getCallbackUrl(): GetCallbackUrlOutput {
    const callbackUrl = !this.appMeta.isProduction
      ? `http://localhost:${DEV_CALLBACK_PORT}/${MCP_CALLBACK_KEY}`
      : `${this.deepLinkService.getProtocol()}://${MCP_CALLBACK_KEY}`;
    return { callbackUrl };
  }

  /**
   * Open the OAuth authorization URL in the browser and wait for the callback.
   * In dev mode, starts a local HTTP server. In production, uses deep links.
   */
  public async openAndWaitForCallback(
    redirectUrl: string,
  ): Promise<OpenAndWaitOutput> {
    try {
      // Cancel any existing pending callback
      this.cancelPending();

      const result = !this.appMeta.isProduction
        ? await this.waitForHttpCallback(redirectUrl)
        : await this.waitForDeepLinkCallback(redirectUrl);

      // Emit event for any subscribers
      this.emit(McpCallbackEvent.OAuthComplete, result);

      return {
        success: result.status === "success",
        installationId: result.installationId,
        error: result.error,
      };
    } catch (error) {
      const errorMsg = error instanceof Error ? error.message : "Unknown error";
      return { success: false, error: errorMsg };
    }
  }

  private handleCallback(searchParams: URLSearchParams): boolean {
    const status = searchParams.get("status") as "success" | "error" | null;
    const installationId = searchParams.get("installation_id") ?? undefined;
    const error = searchParams.get("error") ?? undefined;

    if (!this.pendingCallback) {
      this.log.warn("Received MCP OAuth callback but no pending flow");
      return false;
    }

    const { resolve, timeoutId } = this.pendingCallback;
    clearTimeout(timeoutId);
    this.pendingCallback = null;

    const result: McpCallbackResult = {
      status: status === "success" ? "success" : "error",
      installationId,
      error,
    };
    resolve(result);
    return true;
  }

  /**
   * Wait for callback via deep link (production).
   */
  private async waitForDeepLinkCallback(
    redirectUrl: string,
  ): Promise<McpCallbackResult> {
    return new Promise<McpCallbackResult>((resolve, reject) => {
      const timeoutId = setTimeout(() => {
        this.pendingCallback = null;
        reject(new Error("MCP OAuth authorization timed out"));
      }, OAUTH_TIMEOUT_MS);

      this.pendingCallback = {
        resolve,
        reject,
        timeoutId,
      };

      // Open the browser for authentication
      this.urlLauncher.launch(redirectUrl).catch((error) => {
        clearTimeout(timeoutId);
        this.pendingCallback = null;
        reject(new Error(`Failed to open browser: ${error.message}`));
      });
    });
  }

  /**
   * Wait for callback via the workspace-server HTTP server (development).
   */
  private async waitForHttpCallback(
    redirectUrl: string,
  ): Promise<McpCallbackResult> {
    const abortController = new AbortController();
    this.pendingCallback = {
      resolve: () => {},
      reject: () => {},
      abortController,
    };

    try {
      const params = await this.callbackServer.waitForCallback({
        port: DEV_CALLBACK_PORT,
        path: `/${MCP_CALLBACK_KEY}`,
        timeoutMs: OAUTH_TIMEOUT_MS,
        signal: abortController.signal,
        onListening: () => {
          this.log.info(
            `Dev MCP OAuth callback server listening on port ${DEV_CALLBACK_PORT}`,
          );
          this.urlLauncher.launch(redirectUrl).catch(() => {
            abortController.abort();
          });
        },
        successWhen: (queryParams) => queryParams.get("status") === "success",
      });

      const status = params.get("status");
      return {
        status: status === "success" ? "success" : "error",
        installationId: params.get("installation_id") ?? undefined,
        error: params.get("error") ?? undefined,
      };
    } finally {
      this.pendingCallback = null;
    }
  }

  /**
   * Cancel any pending callback.
   */
  private cancelPending(): void {
    if (this.pendingCallback) {
      if (this.pendingCallback.abortController) {
        this.pendingCallback.abortController.abort();
        this.pendingCallback = null;
      } else {
        if (this.pendingCallback.timeoutId) {
          clearTimeout(this.pendingCallback.timeoutId);
        }
        this.pendingCallback.reject(new Error("MCP OAuth flow cancelled"));
        this.pendingCallback = null;
      }
    }
  }
}
