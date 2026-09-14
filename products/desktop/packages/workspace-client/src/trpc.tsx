import type { AppRouter } from "@posthog/workspace-server/trpc";
import { createTRPCContext } from "@trpc/tanstack-react-query";

export const {
  TRPCProvider: WorkspaceTRPCProvider,
  useTRPC: useWorkspaceTRPC,
} = createTRPCContext<AppRouter>();
