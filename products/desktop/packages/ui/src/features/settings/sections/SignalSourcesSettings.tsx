import { ArrowRightIcon } from "@phosphor-icons/react";
import { DataSourceSetup } from "@posthog/ui/features/inbox/components/DataSourceSetup";
import {
  SignalSourceToggles,
  SignalSourceTogglesSkeleton,
} from "@posthog/ui/features/inbox/components/SignalSourceToggles";
import { useSignalSourceManager } from "@posthog/ui/features/inbox/hooks/useSignalSourceManager";
import { useRepositoryIntegration } from "@posthog/ui/features/integrations/useIntegrations";
import { openSettings } from "@posthog/ui/features/settings/hooks/useOpenSettings";
import { AutostartBaseBranchesSettings } from "@posthog/ui/features/settings/sections/AutostartBaseBranchesSettings";
import { GitHubIntegrationSection } from "@posthog/ui/features/settings/sections/GitHubIntegrationSection";
import { SlackInboxNotificationsSettings } from "@posthog/ui/features/settings/sections/SlackInboxNotificationsSettings";
import { Box, Flex, Text, Tooltip } from "@radix-ui/themes";

interface SignalSourcesSettingsProps {
  /** Slack channel combobox is inside a Radix modal dialog (Inbox configuration). */
  slackNotificationsInModal?: boolean;
  /**
   * Render the Slack inbox-notification config inline. True in the inbox setup
   * flow (where picking a channel is part of onboarding); false in the Settings
   * dialog's Signals section, which links out to the dedicated Slack section.
   */
  showSlackNotifications?: boolean;
}

export function SignalSourcesSettings({
  slackNotificationsInModal = false,
  showSlackNotifications = true,
}: SignalSourcesSettingsProps) {
  const {
    displayValues,
    sourceStates,
    setupSource,
    isLoading,
    handleToggle,
    handleSetup,
    handleSetupComplete,
    handleSetupCancel,
    teamConfig,
    teamConfigLoading,
    handleUpdateAutostartBaseBranches,
  } = useSignalSourceManager();

  const { hasGithubIntegration, isLoadingIntegrations } =
    useRepositoryIntegration();

  return (
    <Flex direction="column" gap="4">
      <Text className="text-(--gray-11) text-sm">
        Connect GitHub and pick which sources to monitor. PostHog will analyze
        activity around the clock and surface ready-to-merge fixes and
        improvements.
      </Text>

      <GitHubIntegrationSection
        hasGithubIntegration={hasGithubIntegration}
        isLoading={isLoadingIntegrations}
      />

      {isLoading ? (
        <SignalSourceTogglesSkeleton />
      ) : (
        <Tooltip
          content="Connect code access to configure Self-driving inputs"
          hidden={hasGithubIntegration}
        >
          <Box>
            <Box
              style={
                !hasGithubIntegration
                  ? { opacity: 0.45, pointerEvents: "none" }
                  : undefined
              }
            >
              {setupSource ? (
                <DataSourceSetup
                  source={setupSource}
                  onComplete={() => void handleSetupComplete()}
                  onCancel={handleSetupCancel}
                />
              ) : (
                <SignalSourceToggles
                  value={displayValues}
                  onToggle={(source, enabled) =>
                    void handleToggle(source, enabled)
                  }
                  disabled={!hasGithubIntegration}
                  sourceStates={sourceStates}
                  onSetup={handleSetup}
                />
              )}
            </Box>
          </Box>
        </Tooltip>
      )}
      <AutostartBaseBranchesSettings
        branches={teamConfig?.autostart_base_branches ?? {}}
        onChange={(next) => void handleUpdateAutostartBaseBranches(next)}
        isLoading={teamConfigLoading}
      />
      {showSlackNotifications ? (
        <SlackInboxNotificationsSettings
          channelComboboxModal={slackNotificationsInModal}
          isLoading={isLoadingIntegrations}
        />
      ) : (
        <Flex
          align="center"
          justify="between"
          gap="2"
          pt="3"
          wrap="wrap"
          style={{ borderTop: "1px dashed var(--gray-5)" }}
        >
          <Flex direction="column" gap="1" className="min-w-0">
            <Text className="font-medium text-(--gray-12) text-sm">
              Slack notifications
            </Text>
            <Text className="text-(--gray-11) text-[13px]">
              Choose where ready inbox reports are posted and who gets pinged.
            </Text>
          </Flex>
          <button
            type="button"
            className="flex shrink-0 cursor-pointer items-center gap-1 border-0 bg-transparent text-[13px] text-accent-11 transition-colors hover:text-accent-12"
            onClick={() => openSettings("slack")}
          >
            Manage in Slack settings
            <ArrowRightIcon size={13} />
          </button>
        </Flex>
      )}
    </Flex>
  );
}
