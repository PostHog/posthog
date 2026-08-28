import type { AppRouter } from "@posthog/workspace-server/trpc";
import {
  createTRPCClient,
  httpBatchLink,
  httpSubscriptionLink,
  splitLink,
} from "@trpc/client";
import superjson from "superjson";

const SECRET_HEADER = "x-workspace-secret";

export interface WorkspaceConnection {
  url: string;
  secret: string;
}

export type WorkspaceClient = ReturnType<typeof createWorkspaceClient>;

/**
 * A workspace client that follows the host's current connection. The
 * workspace-server child can crash and be respawned on a new port with a new
 * secret; a client built once at boot would keep calling the dead port
 * ("fetch failed") for the rest of the app session. This proxy re-reads the
 * connection at the start of every call chain and rebuilds the underlying
 * client whenever it changes. While the server is down (`getConnection`
 * returns null) the last known client is used, so calls fail fast against the
 * old port instead of hanging.
 */
export function createReconnectingWorkspaceClient(
  getConnection: () => WorkspaceConnection | null,
  buildClient: (
    connection: WorkspaceConnection,
  ) => WorkspaceClient = createWorkspaceClient,
): WorkspaceClient {
  let built: {
    connection: WorkspaceConnection;
    client: WorkspaceClient;
  } | null = null;

  const resolve = (): WorkspaceClient => {
    const connection = getConnection() ?? built?.connection;
    if (!connection) {
      throw new Error("workspace-server connection is not established yet");
    }
    if (
      !built ||
      built.connection.url !== connection.url ||
      built.connection.secret !== connection.secret
    ) {
      built = { connection, client: buildClient(connection) };
    }
    return built.client;
  };

  return new Proxy({} as WorkspaceClient, {
    get: (_target, prop) => Reflect.get(resolve() as object, prop),
    has: (_target, prop) => Reflect.has(resolve() as object, prop),
    getPrototypeOf: () => Reflect.getPrototypeOf(resolve() as object),
  });
}

export function createWorkspaceClient(connection: WorkspaceConnection) {
  const url = `${connection.url.replace(/\/$/, "")}/trpc`;
  const headers = { [SECRET_HEADER]: connection.secret };
  const subscriptionUrl = `${url}?secret=${encodeURIComponent(connection.secret)}`;

  return createTRPCClient<AppRouter>({
    links: [
      splitLink({
        condition: (op) => op.type === "subscription",
        true: httpSubscriptionLink({
          url: subscriptionUrl,
          transformer: superjson,
        }),
        false: httpBatchLink({
          url,
          transformer: superjson,
          headers: () => headers,
        }),
      }),
    ],
  });
}
