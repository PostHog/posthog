import type { QueryClient } from "@tanstack/react-query";
import { type ReactNode, useMemo } from "react";
import {
  createLazyWorkspaceClient,
  createWorkspaceClient,
  type WorkspaceConnection,
} from "./client";
import { WorkspaceTRPCProvider } from "./trpc";

const UNAVAILABLE: WorkspaceConnection = {
  url: "http://127.0.0.1:1/trpc-unavailable",
  secret: "",
};

export interface WorkspaceClientProviderProps {
  connection?: WorkspaceConnection | null;
  getConnection?: () => Promise<WorkspaceConnection>;
  queryClient: QueryClient;
  children: ReactNode;
}

export function WorkspaceClientProvider({
  connection,
  getConnection,
  queryClient,
  children,
}: WorkspaceClientProviderProps) {
  const client = useMemo(
    () =>
      getConnection
        ? createLazyWorkspaceClient(getConnection)
        : createWorkspaceClient(connection ?? UNAVAILABLE),
    [connection, getConnection],
  );

  return (
    <WorkspaceTRPCProvider trpcClient={client} queryClient={queryClient}>
      {children}
    </WorkspaceTRPCProvider>
  );
}
