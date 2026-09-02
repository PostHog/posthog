export interface AuthProxyAuth {
  authenticatedFetch(url: string, init?: RequestInit): Promise<Response>;
}
