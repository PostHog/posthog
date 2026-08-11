import { useMeQuery } from "@posthog/ui/features/auth/useMeQuery";
import { SettingRow } from "@posthog/ui/features/settings/SettingRow";
import { useAuthenticatedMutation } from "@posthog/ui/hooks/useAuthenticatedMutation";
import { useAuthenticatedQuery } from "@posthog/ui/hooks/useAuthenticatedQuery";
import { openExternalUrl } from "@posthog/ui/shell/openExternal";
import { Button, Flex, Switch, Text } from "@radix-ui/themes";
import { useQueryClient } from "@tanstack/react-query";

// Server-side, unlike the toggles above it: the DM is sent by a worker, so the preference has to
// be readable when this app is closed.
const SETTING_KEY = "code_comments_slack_dm";

export function SlackCommentNotificationsSettings() {
  const queryClient = useQueryClient();
  const { data: me, isLoading } = useMeQuery();
  const { data: links, isLoading: linksLoading } = useAuthenticatedQuery(
    ["slack-user-integrations"],
    async (client) => await client.listSlackUserIntegrations(),
  );

  const enabled = Boolean(
    (me?.notification_settings as Record<string, unknown> | undefined)?.[
      SETTING_KEY
    ],
  );
  const linked = (links?.length ?? 0) > 0;

  const { mutate, isPending } = useAuthenticatedMutation<void, Error, boolean>(
    async (client, next) =>
      await client.updateNotificationSettings({ [SETTING_KEY]: next }),
    {
      onSuccess: () => {
        void queryClient.invalidateQueries({ queryKey: ["me"] });
      },
    },
  );

  // Slack's OAuth callback tells us which Slack user authorized, so the link is established
  // without anyone entering an ID.
  const { mutate: connect, isPending: connecting } = useAuthenticatedMutation<
    void,
    Error,
    void
  >(async (client) => {
    const { install_url } = await client.startSlackUserIntegrationConnect();
    openExternalUrl(install_url);
  });

  return (
    <>
      <Text className="mt-4 mb-1 block border-gray-6 border-t pt-4 font-medium text-sm">
        Slack
      </Text>
      <Text color="gray" className="mb-1 text-[13px]">
        Comment notifications can also reach you in Slack, so you hear about
        them when PostHog Code isn't open.
      </Text>

      <SettingRow
        label="Slack account"
        description={
          linked
            ? `Connected to ${links?.[0]?.slack_team_name ?? "Slack"}`
            : "Connect your Slack account so we know who to message"
        }
      >
        {linked ? (
          <Text color="gray" className="text-[13px]">
            Connected
          </Text>
        ) : (
          <Button
            size="1"
            disabled={connecting || linksLoading}
            onClick={() => connect()}
          >
            {connecting ? "Opening Slack…" : "Connect Slack"}
          </Button>
        )}
      </SettingRow>

      <SettingRow
        label="Slack DMs for comments"
        description="Get a direct message when someone mentions you, replies to your comment, or comments on something you own"
        noBorder
      >
        <Flex align="center" gap="2">
          <Switch
            checked={enabled}
            onCheckedChange={(next) => mutate(next)}
            disabled={isLoading || isPending || !linked}
            size="1"
          />
        </Flex>
      </SettingRow>
    </>
  );
}
