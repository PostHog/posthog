import { ArrowSquareOutIcon } from "@phosphor-icons/react";
import { useAuthStateValue } from "@posthog/ui/features/auth/store";
import { useIntegrations } from "@posthog/ui/features/integrations/useIntegrations";
import { openUrlInBrowser } from "@posthog/ui/utils/browser";
import { getPostHogUrl } from "@posthog/ui/utils/urls";
import { Button, Flex, Text, Tooltip } from "@radix-ui/themes";
import { SlackInboxNotificationsSettings } from "./SlackInboxNotificationsSettings";

export function SlackSettings() {
  const projectId = useAuthStateValue((s) => s.currentProjectId);
  const cloudRegion = useAuthStateValue((s) => s.cloudRegion);
  const { isLoading } = useIntegrations();

  const slackSettingsUrl = projectId
    ? getPostHogUrl(
        `/project/${projectId}/settings/project-integrations#integration-slack`,
        cloudRegion,
      )
    : null;

  const manageButton = (
    <Button
      size="1"
      disabled={!slackSettingsUrl}
      onClick={() => {
        if (slackSettingsUrl) void openUrlInBrowser(slackSettingsUrl);
      }}
    >
      <ArrowSquareOutIcon size={12} />
      Manage in PostHog Web
    </Button>
  );

  const manageButtonWithTooltip = slackSettingsUrl ? (
    manageButton
  ) : (
    <Tooltip content="Sign in to a PostHog project to manage the Slack integration">
      {manageButton}
    </Tooltip>
  );

  return (
    <Flex direction="column" gap="3">
      <Text className="text-(--gray-11) text-[13px]">
        Connect Slack to PostHog to kick off tasks like pull requests directly
        from Slack.
      </Text>

      <Flex>{manageButtonWithTooltip}</Flex>

      <SlackInboxNotificationsSettings
        isLoading={isLoading}
        showHeader={false}
      />
    </Flex>
  );
}
