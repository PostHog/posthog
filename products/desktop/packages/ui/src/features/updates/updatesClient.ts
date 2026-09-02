import type {
  CheckForUpdatesOutput,
  UpdatesStatusPayload,
} from "@posthog/core/updates/schemas";

interface Subscriber<T> {
  onData: (data: T) => void;
  onError?: (error: unknown) => void;
}

export interface UpdatesClient {
  install(): Promise<{ installed: boolean }>;
  check(): Promise<CheckForUpdatesOutput>;
  isEnabled(): Promise<{ enabled: boolean }>;
  getStatus(): Promise<UpdatesStatusPayload>;
  onStatus(sub: Subscriber<UpdatesStatusPayload>): { unsubscribe: () => void };
  onReady(sub: Subscriber<{ version: string | null }>): {
    unsubscribe: () => void;
  };
  onCheckFromMenu(sub: Subscriber<void>): { unsubscribe: () => void };
}

export const UPDATES_CLIENT = Symbol.for("posthog.ui.UpdatesClient");
