import type { AppRouter } from "@posthog/workspace-server/trpc";
import {
  createTRPCClient,
  httpBatchLink,
  httpSubscriptionLink,
  splitLink,
} from "@trpc/client";
import superjson from "superjson";

const SECRET_HEADER = "x-workspace-secret";
const UNRESOLVED_WORKSPACE_URL = "http://workspace-server.invalid/trpc";

export interface WorkspaceConnection {
  url: string;
  secret: string;
}

export type WorkspaceClient = ReturnType<typeof createWorkspaceClient>;

export function createWorkspaceClient(connection: WorkspaceConnection) {
  return createLazyWorkspaceClient(() => Promise.resolve(connection));
}

export function createLazyWorkspaceClient(
  getConnection: () => Promise<WorkspaceConnection>,
) {
  const fetchWithConnection = async (
    input: { url: string } | URL | string,
    init?: RequestInit,
  ) => {
    const connection = await getConnection();
    const unresolvedUrl = new URL(
      typeof input === "string"
        ? input
        : input instanceof URL
          ? input.href
          : input.url,
    );
    const resolvedUrl = new URL(
      `${unresolvedUrl.pathname}${unresolvedUrl.search}`,
      connection.url,
    );
    const headers = new Headers(init?.headers);
    headers.set(SECRET_HEADER, connection.secret);
    return globalThis.fetch(resolvedUrl, { ...init, headers });
  };

  return createTRPCClient<AppRouter>({
    links: [
      splitLink({
        condition: (op) => op.type === "subscription",
        true: httpSubscriptionLink({
          url: async () => {
            const connection = await getConnection();
            return `${connection.url.replace(/\/$/, "")}/trpc?secret=${encodeURIComponent(connection.secret)}`;
          },
          transformer: superjson,
        }),
        false: httpBatchLink({
          url: UNRESOLVED_WORKSPACE_URL,
          transformer: superjson,
          fetch: fetchWithConnection as NonNullable<
            Parameters<typeof httpBatchLink>[0]["fetch"]
          >,
        }),
      }),
    ],
  });
}
