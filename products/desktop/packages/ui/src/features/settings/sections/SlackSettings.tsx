import { ArrowSquareOutIcon } from "@phosphor-icons/react";
import { Button, Text } from "@posthog/quill";
import { useAuthStateValue } from "@posthog/ui/features/auth/store";
import { useIntegrations } from "@posthog/ui/features/integrations/useIntegrations";
import { SlackCommentNotificationsSettings } from "@posthog/ui/features/settings/sections/SlackCommentNotificationsSettings";
import { openUrlInBrowser } from "@posthog/ui/utils/browser";
import { getPostHogUrl } from "@posthog/ui/utils/urls";
import { SlackInboxNotificationsSettings } from "./SlackInboxNotificationsSettings";

const SLACK_DOCS_URL = "https://posthog.com/docs/libraries/slack";
const SETTINGS_REFETCH_INTERVAL_MS = 30_000;

export function SlackSettings() {
  const projectId = useAuthStateValue((s) => s.currentProjectId);
  const cloudRegion = useAuthStateValue((s) => s.cloudRegion);
  const { isLoading } = useIntegrations({
    refetchInterval: SETTINGS_REFETCH_INTERVAL_MS,
  });

  const slackSettingsUrl = projectId
    ? getPostHogUrl(
        `/project/${projectId}/settings/project-integrations#integration-slack`,
        cloudRegion,
      )
    : null;

  return (
    <div className="flex flex-col gap-3">
      <Text size="xs" variant="muted">
        Connect a Slack workspace so reports can post to channels, reviewers get
        pinged, and you can kick off tasks like pull requests from Slack.
      </Text>

      <SlackInboxNotificationsSettings
        isLoading={isLoading}
        showHeader={false}
      />

      <SlackCommentNotificationsSettings />

      <div className="flex flex-wrap items-center gap-3">
        {slackSettingsUrl ? (
          <Button
            type="button"
            variant="outline"
            size="xs"
            onClick={() => void openUrlInBrowser(slackSettingsUrl)}
          >
            <ArrowSquareOutIcon size={12} />
            Advanced settings in PostHog
          </Button>
        ) : null}
        <button
          type="button"
          onClick={() => void openUrlInBrowser(SLACK_DOCS_URL)}
          className="inline-flex cursor-pointer items-center gap-1 border-0 bg-transparent p-0 text-(--accent-11) text-xs no-underline hover:text-(--accent-12)"
        >
          Learn about the Slack integration
          <ArrowSquareOutIcon size={11} />
        </button>
      </div>
    </div>
  );
}
