import type {
  PiRpcClient,
  PiRpcClientOptions,
} from "@posthog/agent/pi/rpc-client";
import type { PiRuntime } from "@posthog/agent/pi/runtime";
import type { TaskContextInput } from "@posthog/agent/pi/task-system-prompt";

export interface PiRpcClientFactory {
  create(
    input: Pick<
      PiRpcClientOptions,
      "model" | "sessionFile" | "projectTrusted"
    > & {
      taskContext: TaskContextInput;
    },
  ): Promise<PiRpcClient>;
}

export const PI_RPC_CLIENT_FACTORY = Symbol.for(
  "posthog.workspace.piRpcClientFactory",
);

export interface PiRuntimeFactory {
  create(
    input: Parameters<PiRpcClientFactory["create"]>[0],
  ): Promise<PiRuntime>;
}

export const PI_RUNTIME_FACTORY = Symbol.for(
  "posthog.workspace.piRuntimeFactory",
);

export const PI_SESSION_SERVICE = Symbol.for(
  "posthog.workspace.piSessionService",
);
