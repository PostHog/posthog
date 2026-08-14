import { resolveService } from "@posthog/di/container";
import {
  HOST_TRPC_CLIENT,
  type HostTrpcClient,
} from "@posthog/host-router/client";
import type { UpdatesClient } from "./updatesClient";

function host(): HostTrpcClient {
  return resolveService<HostTrpcClient>(HOST_TRPC_CLIENT);
}

export const updatesClient: UpdatesClient = {
  install: () => host().updates.install.mutate(),
  check: () => host().updates.check.mutate(),
  isEnabled: () => host().updates.isEnabled.query(),
  getStatus: () => host().updates.getStatus.query(),
  onStatus: (sub) => host().updates.onStatus.subscribe(undefined, sub),
  onReady: (sub) =>
    host().updates.onReady.subscribe(undefined, {
      onData: (data) => sub.onData({ version: data.version }),
      onError: sub.onError,
    }),
  onCheckFromMenu: (sub) =>
    host().updates.onCheckFromMenu.subscribe(undefined, {
      onData: () => sub.onData(),
      onError: sub.onError,
    }),
};
