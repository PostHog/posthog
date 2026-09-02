import { resolveService } from "@posthog/di/container";
import {
  HOST_TRPC_CLIENT,
  type HostTrpcClient,
} from "@posthog/host-router/client";

export interface MessageBoxOptions {
  type?: "none" | "info" | "error" | "question" | "warning";
  title?: string;
  message?: string;
  detail?: string;
  buttons?: string[];
  defaultId?: number;
  cancelId?: number;
}

export async function showMessageBox(
  options: MessageBoxOptions,
): Promise<{ response: number }> {
  if (document.activeElement instanceof HTMLElement) {
    document.activeElement.blur();
  }

  return resolveService<HostTrpcClient>(
    HOST_TRPC_CLIENT,
  ).os.showMessageBox.mutate({ options });
}
