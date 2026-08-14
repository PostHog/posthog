import { useServiceOptional } from "@posthog/di/react";
import {
  HOST_CAPABILITIES,
  type HostCapabilities,
} from "@posthog/platform/host-capabilities";

// Hosts that predate the token (and Storybook/tests, which have no host binding)
// default to the desktop posture, so existing behavior is unchanged unless a host
// explicitly opts out.
const DEFAULT_CAPABILITIES: HostCapabilities = { localWorkspaces: true };

/** Read the current host's coarse capabilities. Safe when unbound. */
export function useHostCapabilities(): HostCapabilities {
  return (
    useServiceOptional<HostCapabilities>(HOST_CAPABILITIES) ??
    DEFAULT_CAPABILITIES
  );
}
