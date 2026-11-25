import type { AuthProxyService } from "./auth-proxy";
import type { GatewayCredentialSource } from "./ports";

export interface ResolvedGatewayProxy {
  proxyUrl: string;
}

/** Loopback gateway session; with no project it lists models but refuses inference. */
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
