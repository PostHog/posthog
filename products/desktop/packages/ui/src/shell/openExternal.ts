import { resolveService } from "@posthog/di/container";
import {
  HOST_TRPC_CLIENT,
  type HostTrpcClient,
} from "@posthog/host-router/client";

export function openExternalUrl(url: string): void {
  void resolveService<HostTrpcClient>(HOST_TRPC_CLIENT).os.openExternal.mutate({
    url,
  });
}

export function showLogFolder(): void {
  void resolveService<HostTrpcClient>(
    HOST_TRPC_CLIENT,
  ).os.showLogFolder.mutate();
}
