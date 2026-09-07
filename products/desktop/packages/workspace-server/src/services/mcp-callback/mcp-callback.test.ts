import type { RootLogger } from "@posthog/di/logger";
import type { IAppMeta } from "@posthog/platform/app-meta";
import type { IDeepLinkRegistry } from "@posthog/platform/deep-link";
import type { IUrlLauncher } from "@posthog/platform/url-launcher";
import {
  parseDesktopPreviewManifest,
  registerPreviewDeployment,
} from "@posthog/shared";
import { afterEach, describe, expect, it, vi } from "vitest";
import { McpCallbackService } from "./mcp-callback";
import type { McpCallbackServer } from "./mcp-callback-server";

const PREVIEW_SCHEME = "posthog-code-preview-pr-123";

function buildService(protocol: string): McpCallbackService {
  const deepLinks = {
    registerHandler: vi.fn(),
    unregisterHandler: vi.fn(),
    getProtocol: () => protocol,
    handleUrl: vi.fn(),
  } satisfies IDeepLinkRegistry;
  const logger = {
    scope: () => ({ info: vi.fn(), warn: vi.fn(), error: vi.fn() }),
  } as unknown as RootLogger;
  return new McpCallbackService(
    deepLinks,
    {} as IUrlLauncher,
    {} as McpCallbackServer,
    // A preview is a packaged build, so it looks like production here.
    { isProduction: true } as IAppMeta,
    logger,
  );
}

function registerPreview(): void {
  registerPreviewDeployment(
    parseDesktopPreviewManifest({
      schemaVersion: 1,
      kind: "desktop-preview",
      repository: "PostHog/posthog",
      prNumber: 123,
      commitSha: "1".repeat(40),
      backendOrigin: "https://preview.example.com",
      gatewayBaseUrl: null,
      oauthClientId: "example-public-client-id-1234",
    }),
  );
}

describe("McpCallbackService.getCallbackUrl", () => {
  afterEach(() => {
    registerPreviewDeployment(null);
  });

  // The PR scheme is not on the backend's MCP callback allowlist, so sending it
  // fails every server connection with "Invalid callback URL" before OAuth
  // starts. Sign-in falls back to loopback for the same reason.
  it("uses the loopback callback in a preview build", () => {
    registerPreview();

    const { callbackUrl } = buildService(PREVIEW_SCHEME).getCallbackUrl();

    expect(callbackUrl).toBe("http://localhost:8238/mcp-oauth-complete");
  });

  it("keeps the deep-link callback for an ordinary packaged build", () => {
    const { callbackUrl } = buildService("posthog-code").getCallbackUrl();

    expect(callbackUrl).toBe("posthog-code://mcp-oauth-complete");
  });
});
