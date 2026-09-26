export interface AuthProxyAuth {
  authenticatedFetch(url: string, init?: RequestInit): Promise<Response>;
}

export type GatewayCredential =
  | { mode: "legacy"; reason: string }
  | { mode: "blocked"; reason: "credit_bucket_exhausted"; detail: string }
  | {
      mode: "go";
      gatewayUrl: string;
      token: string;
      teamId: number;
      projectId: number;
      allowedModels: string[] | null;
      productModels: string[];
    };

export type GatewayRemintReason = "unauthorized" | "token_cap_exceeded";

export interface GatewayCredentialSource {
  getRoute(
    projectId: number,
    options?: { awaitRecheck?: boolean },
  ): Promise<GatewayCredential>;
  remint(
    reason: GatewayRemintReason,
    staleToken: string,
    projectId: number,
  ): Promise<GatewayCredential | null>;
  fallBack(token: string, projectId: number): void;
}
