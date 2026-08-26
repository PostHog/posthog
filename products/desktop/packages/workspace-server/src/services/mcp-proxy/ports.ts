export interface McpProxyAuth {
  authenticatedFetch(url: string, init?: RequestInit): Promise<Response>;
  refreshAccessToken(): Promise<unknown>;
}
