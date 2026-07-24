import { AGENT_PLATFORM_FLAG } from "@posthog/ui/features/agent-applications/featureFlag";
import { useFeatureFlag } from "@posthog/ui/features/feature-flags/useFeatureFlag";
import { Flex, Text } from "@radix-ui/themes";
import { createFileRoute, Outlet } from "@tanstack/react-router";

export const Route = createFileRoute("/code/agents/applications")({
  component: ApplicationsGate,
});

/**
 * Gates the entire Applications surface (list + per-agent detail) behind the
 * `agent-platform` flag. When disabled the tab is also hidden from the agents
 * chrome; direct navigation here lands on this placeholder.
 */
function ApplicationsGate() {
  const enabled = useFeatureFlag(AGENT_PLATFORM_FLAG);
  if (!enabled) {
    return (
      <Flex align="center" justify="center" className="h-full min-h-0 p-6">
        <Text className="max-w-sm text-center text-[13px] text-gray-10 leading-snug">
          Agent applications aren't available yet.
        </Text>
      </Flex>
    );
  }
  return <Outlet />;
}
