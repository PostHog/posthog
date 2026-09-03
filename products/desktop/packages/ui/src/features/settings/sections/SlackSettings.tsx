import { ArrowSquareOutIcon } from "@phosphor-icons/react";
import { Button, Spinner } from "@posthog/quill";
import { useAuthStateValue } from "@posthog/ui/features/auth/store";
import { useIntegrationSelectors } from "@posthog/ui/features/integrations/store";
import { useIntegrations } from "@posthog/ui/features/integrations/useIntegrations";
import { useSlackConnect } from "@posthog/ui/features/integrations/useSlackConnect";
import { SettingsSection } from "@posthog/ui/features/settings/components/SettingsCard";
import { SlackCommentNotificationsSettings } from "@posthog/ui/features/settings/sections/SlackCommentNotificationsSettings";
import { openUrlInBrowser } from "@posthog/ui/utils/browser";
import { getPostHogUrl } from "@posthog/ui/utils/urls";
import { SlackInboxNotificationsSettings } from "./SlackInboxNotificationsSettings";
import {
  SlackWorkspaceConnection,
  SlackWorkspaceConnectionCallouts,
} from "./SlackWorkspaceConnection";

const SLACK_DOCS_URL = "https://posthog.com/docs/libraries/slack?tab=Desktop";
const SETTINGS_REFETCH_INTERVAL_MS = 30_000;

export function SlackSettings() {
  const projectId = useAuthStateValue((s) => s.currentProjectId);
  const cloudRegion = useAuthStateValue((s) => s.cloudRegion);
  const { isLoading } = useIntegrations({
    refetchInterval: SETTINGS_REFETCH_INTERVAL_MS,
  });
  const { hasSlackIntegration } = useIntegrationSelectors();
  const slackConnect = useSlackConnect();

  const slackSettingsUrl = projectId
    ? getPostHogUrl(
        `/project/${projectId}/settings/project-integrations#integration-slack`,
        cloudRegion,
      )
    : null;

  return (
    <div className="flex flex-col gap-7">
      <SettingsSection
        label="Workspace connection"
        description="Connect a Slack workspace so reports can post to channels, reviewers get pinged, and you can kick off tasks from Slack"
        action={
          !isLoading && hasSlackIntegration ? (
            <Button
              type="button"
              variant="outline"
              size="sm"
              disabled={slackConnect.isConnecting}
              onClick={() => {
                void slackConnect.connect();
              }}
            >
              {slackConnect.isConnecting ? (
                <Spinner />
              ) : (
                <ArrowSquareOutIcon size={12} />
              )}
              {slackConnect.isConnecting
                ? "Waiting…"
                : "Connect another workspace"}
            </Button>
          ) : undefined
        }
      >
        <SlackWorkspaceConnection
          slackConnect={slackConnect}
          isLoading={isLoading}
          showConnectAnother={false}
        />
        <SlackWorkspaceConnectionCallouts slackConnect={slackConnect} />
      </SettingsSection>

      {hasSlackIntegration ? (
        <SettingsSection
          label="Self-driving notifications"
          description={
            <>
              New Self-driving reports are posted to Slack with the suggested
              reviewers @mentioned. PostHog must be in the channel, so invite it
              with <code className="text-[12px]">/invite @PostHog</code>.
            </>
          }
        >
          <SlackInboxNotificationsSettings
            isLoading={isLoading}
            showHeader={false}
            showWorkspaceConnection={false}
          />
        </SettingsSection>
      ) : null}

      <SlackCommentNotificationsSettings />

      <div className="flex flex-wrap items-center gap-3">
        {slackSettingsUrl ? (
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => void openUrlInBrowser(slackSettingsUrl)}
          >
            <ArrowSquareOutIcon size={12} />
            Advanced settings in PostHog
          </Button>
        ) : null}
        <button
          type="button"
          onClick={() => void openUrlInBrowser(SLACK_DOCS_URL)}
          className="ml-auto inline-flex cursor-pointer items-center gap-1 border-0 bg-transparent p-0 text-muted-foreground text-xs no-underline hover:text-foreground"
        >
          Learn about the Slack integration
          <ArrowSquareOutIcon size={11} />
        </button>
      </div>
    </div>
  );
}
