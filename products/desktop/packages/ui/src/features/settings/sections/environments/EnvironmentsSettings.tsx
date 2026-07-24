import { Cloud, HardDrives } from "@phosphor-icons/react";
import { useSettingsPageStore } from "@posthog/ui/features/settings/stores/settingsPageStore";
import { navigateToSettings } from "@posthog/ui/router/navigationBridge";
import { useHostCapabilities } from "@posthog/ui/shell/useHostCapabilities";
import { Flex, SegmentedControl, Text } from "@radix-ui/themes";
import { useRouterState } from "@tanstack/react-router";
import { CloudEnvironmentsSettings } from "./CloudEnvironmentsSettings";
import { LocalEnvironmentsSettings } from "./LocalEnvironmentsSettings";

type Segment = "local" | "cloud";

export function EnvironmentsSettings() {
  const formMode = useSettingsPageStore((s) => s.formMode);
  // Cloud-only hosts (web) have no local project environments (only sandboxes),
  // so drop the local/cloud toggle and show cloud environments only.
  const { localWorkspaces } = useHostCapabilities();
  const activeCategory = useRouterState({
    select: (s) => {
      const match = s.matches.find((m) => m.routeId === "/settings/$category");
      const params = match?.params as { category?: string } | undefined;
      return params?.category ?? "environments";
    },
  });

  const segment: Segment =
    !localWorkspaces || activeCategory === "cloud-environments"
      ? "cloud"
      : "local";

  const handleSegmentChange = (value: string) => {
    // Replace rather than push so switching tabs doesn't pile up history
    // entries that "Back to app" would otherwise step back through.
    navigateToSettings(
      value === "cloud" ? "cloud-environments" : "environments",
      { replace: true },
    );
  };

  return (
    <Flex direction="column" gap="4">
      {!formMode && !localWorkspaces && (
        <Text color="gray" className="text-[13px]">
          A cloud environment configures the remote sandbox the agent works
          inside when you start a task.
        </Text>
      )}
      {!formMode && localWorkspaces && (
        <>
          <Text color="gray" className="text-[13px]">
            An environment defines what the agent works inside when you start a
            task.{" "}
            <Text color="gray" className="font-medium text-[13px]">
              Local
            </Text>{" "}
            environments prepare a project on your machine;{" "}
            <Text color="gray" className="font-medium text-[13px]">
              cloud
            </Text>{" "}
            environments configure remote sandboxes.
          </Text>
          <SegmentedControl.Root
            value={segment}
            onValueChange={handleSegmentChange}
            size="2"
          >
            <SegmentedControl.Item value="local">
              <Flex align="center" gap="2">
                <HardDrives size={14} />
                <Text>Local</Text>
              </Flex>
            </SegmentedControl.Item>
            <SegmentedControl.Item value="cloud">
              <Flex align="center" gap="2">
                <Cloud size={14} />
                <Text>Cloud</Text>
              </Flex>
            </SegmentedControl.Item>
          </SegmentedControl.Root>
        </>
      )}

      {segment === "cloud" ? (
        <CloudEnvironmentsSettings />
      ) : (
        <LocalEnvironmentsSettings />
      )}
    </Flex>
  );
}
