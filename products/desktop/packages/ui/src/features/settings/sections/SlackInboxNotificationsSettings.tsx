import { SlackLogoIcon } from "@phosphor-icons/react";
import {
  deriveEffectiveIntegrationId,
  getSlackIntegrationLabel,
} from "@posthog/core/settings/slackNotificationTarget";
import { useSignalSourceManager } from "@posthog/ui/features/inbox/hooks/useSignalSourceManager";
import { useIntegrationSelectors } from "@posthog/ui/features/integrations/store";
import { SettingsOptionSelect } from "@posthog/ui/features/settings/SettingsOptionSelect";
import { SignalDefaultChannelSettings } from "@posthog/ui/features/settings/sections/SignalDefaultChannelSettings";
import { SignalSlackNotificationsSettings } from "@posthog/ui/features/settings/sections/SignalSlackNotificationsSettings";
import {
  SlackWorkspaceConnection,
  SlackWorkspaceConnectionCallouts,
} from "@posthog/ui/features/settings/sections/SlackWorkspaceConnection";
import { Box, Flex, Text } from "@radix-ui/themes";
import { useMemo } from "react";

const WORKSPACE_CONTROL_CLASS = "min-w-[160px] max-w-[240px]";

interface SlackInboxNotificationsSettingsProps {
  channelComboboxModal?: boolean;
  isLoading?: boolean;
  /** When false, omit the section header (parent already titles this block). */
  showHeader?: boolean;
  /** When false, omit the dashed top rule (nested under a parent section). */
  showTopBorder?: boolean;
}

export function SlackInboxNotificationsSettings({
  channelComboboxModal = false,
  isLoading = false,
  showHeader = true,
  showTopBorder = true,
}: SlackInboxNotificationsSettingsProps) {
  const { slackIntegrations, hasSlackIntegration } = useIntegrationSelectors();
  const { userAutonomyConfig, handleUpdateSlackNotifications } =
    useSignalSourceManager();

  // Workspace is shared by both the team default and the per-user channel. We
  // default to the only workspace when there's a single one; otherwise the user
  // picks (which also persists their personal notification integration).
  const selectedIntegrationId =
    userAutonomyConfig?.slack_notification_integration_id ?? null;
  const effectiveIntegrationId = deriveEffectiveIntegrationId(
    selectedIntegrationId,
    slackIntegrations,
  );

  const integrationOptions = useMemo(
    () =>
      slackIntegrations.map((integration) => ({
        value: String(integration.id),
        label: getSlackIntegrationLabel(integration),
      })),
    [slackIntegrations],
  );

  const onIntegrationChange = (value: string) => {
    const integrationId = Number(value);
    if (!Number.isFinite(integrationId)) return;
    // Switching workspaces clears the personal channel — the previously picked
    // channel won't exist in the new workspace.
    void handleUpdateSlackNotifications({ integrationId, channel: null });
  };

  const topBorderClass = showTopBorder
    ? "border-(--gray-5) border-t border-dashed pt-3"
    : "";

  return (
    <Flex direction="column" gap="3" className={topBorderClass}>
      {showHeader ? (
        <>
          <Flex align="center" gap="2">
            <Box className="shrink-0 text-(--gray-11)">
              <SlackLogoIcon size={16} />
            </Box>
            <Text className="font-medium text-(--gray-12) text-sm">
              Inbox notifications
            </Text>
          </Flex>
          <Text className="text-(--gray-11) text-[13px]">
            New inbox reports are posted to Slack with the suggested reviewers
            @mentioned. PostHog must be in the channel, so invite it with{" "}
            <code className="text-[13px]">/invite @PostHog</code>.
          </Text>
        </>
      ) : null}

      <SlackWorkspaceConnection isLoading={isLoading} />
      <SlackWorkspaceConnectionCallouts />

      {!isLoading && hasSlackIntegration ? (
        <Flex align="center" gap="2" pt="2" className="min-w-0">
          <Text className="shrink-0 text-(--gray-11) text-[12px]">
            Workspace
          </Text>
          {slackIntegrations.length > 1 ? (
            <SettingsOptionSelect
              value={
                effectiveIntegrationId ? String(effectiveIntegrationId) : ""
              }
              options={integrationOptions}
              ariaLabel="Slack workspace"
              placeholder="Select workspace"
              className={WORKSPACE_CONTROL_CLASS}
              onValueChange={onIntegrationChange}
            />
          ) : slackIntegrations[0] ? (
            <Text className="truncate font-medium text-(--gray-12) text-[13px]">
              {getSlackIntegrationLabel(slackIntegrations[0])}
            </Text>
          ) : null}
        </Flex>
      ) : null}

      <SignalDefaultChannelSettings
        integrationId={effectiveIntegrationId}
        channelComboboxModal={channelComboboxModal}
        isLoading={isLoading}
      />
      <SignalSlackNotificationsSettings
        integrationId={effectiveIntegrationId}
        channelComboboxModal={channelComboboxModal}
        isLoading={isLoading}
        hideWorkspaceConnect
      />
    </Flex>
  );
}
