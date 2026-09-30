export interface AuthProxyAuth {
  authenticatedFetch(url: string, init?: RequestInit): Promise<Response>;
}

export const AUTH_PROXY_PLACEHOLDER_CREDENTIAL = "posthog-code-auth-proxy";
