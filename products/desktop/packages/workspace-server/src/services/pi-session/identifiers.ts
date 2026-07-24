import type {
  PiRpcClient,
  PiRpcClientOptions,
} from "@posthog/agent/pi/rpc-client";
import type { PiRuntime } from "@posthog/agent/pi/runtime";

export interface PiRpcClientFactory {
  create(
    input: Pick<PiRpcClientOptions, "cwd" | "model" | "sessionFile">,
  ): Promise<PiRpcClient>;
}

export const PI_RPC_CLIENT_FACTORY = Symbol.for(
  "posthog.workspace.piRpcClientFactory",
);

export interface PiRuntimeFactory {
  create(input: {
    cwd: string;
    model?: string;
    sessionFile?: string;
  }): Promise<PiRuntime>;
}

export const PI_RUNTIME_FACTORY = Symbol.for(
  "posthog.workspace.piRuntimeFactory",
);

export const PI_SESSION_SERVICE = Symbol.for(
  "posthog.workspace.piSessionService",
);
