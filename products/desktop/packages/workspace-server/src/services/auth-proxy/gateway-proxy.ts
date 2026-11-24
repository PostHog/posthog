import type { AuthProxyService } from "./auth-proxy";
import type { GatewayCredentialSource } from "./ports";

export interface ResolvedGatewayProxy {
  proxyUrl: string;
}

/**
 * The loopback gateway session for a project. With no project selected the
 * session still lists models, and refuses inference with a reason the caller
 * can show.
 */
export async function resolveGatewayProxy(input: {
  authProxy: AuthProxyService;
  source: GatewayCredentialSource | undefined;
  aiGatewayUrl: string;
  projectId: number | null;
  headers?: Record<string, string>;
  awaitRecheck?: boolean;
}): Promise<ResolvedGatewayProxy> {
  const { authProxy, source, aiGatewayUrl, projectId, headers } = input;
  // The session settles each request's route and answers a refusal itself.
  if (source && projectId !== null) {
    await source
      .getRoute(projectId, { awaitRecheck: input.awaitRecheck ?? true })
      .catch(() => null);
  }
  return {
    proxyUrl: await authProxy.startGatewaySession({
      projectId,
      aiGatewayUrl,
      headers,
    }),
  };
}
