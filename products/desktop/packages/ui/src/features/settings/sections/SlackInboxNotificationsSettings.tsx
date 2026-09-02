import { SlackLogoIcon } from "@phosphor-icons/react";
import {
  deriveEffectiveIntegrationId,
  getSlackIntegrationLabel,
} from "@posthog/core/settings/slackNotificationTarget";
import { useSignalSourceManager } from "@posthog/ui/features/inbox/hooks/useSignalSourceManager";
import { useIntegrationSelectors } from "@posthog/ui/features/integrations/store";
import {
  SettingsCard,
  SettingsCardRow,
} from "@posthog/ui/features/settings/components/SettingsCard";
import { SettingsOptionSelect } from "@posthog/ui/features/settings/SettingsOptionSelect";
import { SignalDefaultChannelSettings } from "@posthog/ui/features/settings/sections/SignalDefaultChannelSettings";
import { SignalSlackNotificationsSettings } from "@posthog/ui/features/settings/sections/SignalSlackNotificationsSettings";
import { SlackWorkspaceConnectionBlock } from "@posthog/ui/features/settings/sections/SlackWorkspaceConnection";
import { useMemo } from "react";

interface SlackInboxNotificationsSettingsProps {
  channelComboboxModal?: boolean;
  isLoading?: boolean;
  /** When false, omit the section header (parent already titles this block). */
  showHeader?: boolean;
  /** When false, omit the workspace rows (a parent section renders them). */
  showWorkspaceConnection?: boolean;
}

export function SlackInboxNotificationsSettings({
  channelComboboxModal = false,
  isLoading = false,
  showHeader = true,
  showWorkspaceConnection = true,
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

  const showConfiguration = isLoading || hasSlackIntegration;

  return (
    <div className="flex flex-col gap-3">
      {showHeader ? (
        <div className="flex flex-col gap-1">
          <div className="flex items-center gap-2">
            <span className="shrink-0 text-(--gray-11)">
              <SlackLogoIcon size={16} />
            </span>
            <span className="font-medium text-(--gray-12) text-sm">
              Self-driving notifications
            </span>
          </div>
          <p className="m-0 text-(--gray-11) text-[13px]">
            New Self-driving reports are posted to Slack with the suggested
            reviewers @mentioned. PostHog must be in the channel, so invite it
            with <code className="text-[13px]">/invite @PostHog</code>.
          </p>
        </div>
      ) : null}

      {showWorkspaceConnection ? (
        <SlackWorkspaceConnectionBlock isLoading={isLoading} />
      ) : null}

      {showConfiguration ? (
        <SettingsCard>
          {!isLoading && slackIntegrations.length > 1 ? (
            <SettingsCardRow
              label="Workspace"
              description="Channels below are listed from this workspace"
            >
              <SettingsOptionSelect
                value={
                  effectiveIntegrationId ? String(effectiveIntegrationId) : ""
                }
                options={integrationOptions}
                ariaLabel="Slack workspace"
                placeholder="Select workspace"
                className="min-w-[160px] max-w-[240px]"
                onValueChange={onIntegrationChange}
              />
            </SettingsCardRow>
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
          />
        </SettingsCard>
      ) : null}
    </div>
  );
}
