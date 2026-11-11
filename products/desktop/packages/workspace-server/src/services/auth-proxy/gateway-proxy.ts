import type { AuthProxyService } from "./auth-proxy";
import type { GatewayCredentialSource } from "./ports";

export const NO_PROJECT_GATEWAY_ERROR =
  "Select a PostHog project to use the PostHog gateway.";

export interface ResolvedGatewayProxy {
  proxyUrl: string;
  mode: "go";
}

export async function resolveGatewayProxy(input: {
  authProxy: AuthProxyService;
  source: GatewayCredentialSource | undefined;
  projectId: number | null;
  headers?: Record<string, string>;
  awaitRecheck?: boolean;
}): Promise<ResolvedGatewayProxy> {
  const { authProxy, source, projectId, headers } = input;
  if (projectId === null) {
    throw new Error(NO_PROJECT_GATEWAY_ERROR);
  }
  // The session settles each request's route and answers a refusal itself.
  await source
    ?.getRoute(projectId, { awaitRecheck: input.awaitRecheck ?? true })
    .catch(() => null);
  return {
    proxyUrl: await authProxy.startGatewaySession({ projectId, headers }),
    mode: "go",
  };
}
