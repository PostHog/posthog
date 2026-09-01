import type { QueryClient } from "@tanstack/react-query";
import { type ReactNode, useMemo } from "react";
import { createWorkspaceClient, type WorkspaceConnection } from "./client";
import { WorkspaceTRPCProvider } from "./trpc";

const UNAVAILABLE: WorkspaceConnection = {
  url: "http://127.0.0.1:1/trpc-unavailable",
  secret: "",
};

export interface WorkspaceClientProviderProps {
  connection: WorkspaceConnection | null | undefined;
  queryClient: QueryClient;
  children: ReactNode;
}

export function WorkspaceClientProvider({
  connection,
  queryClient,
  children,
}: WorkspaceClientProviderProps) {
  const client = useMemo(
    () => createWorkspaceClient(connection ?? UNAVAILABLE),
    [connection],
  );

  return (
    <WorkspaceTRPCProvider trpcClient={client} queryClient={queryClient}>
      {children}
    </WorkspaceTRPCProvider>
  );
}
