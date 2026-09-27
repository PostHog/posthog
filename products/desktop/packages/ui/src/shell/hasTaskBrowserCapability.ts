import type { HostCapabilities } from "@posthog/platform/host-capabilities";

export function hasTaskBrowserCapability(
  capabilities: HostCapabilities | null | undefined,
): boolean {
  return capabilities?.taskBrowser === true;
}
