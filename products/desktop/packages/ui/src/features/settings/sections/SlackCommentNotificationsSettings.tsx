import { useMeQuery } from "@posthog/ui/features/auth/useMeQuery";
import { SettingRow } from "@posthog/ui/features/settings/SettingRow";
import { useAuthenticatedMutation } from "@posthog/ui/hooks/useAuthenticatedMutation";
import { Switch, Text } from "@radix-ui/themes";
import { useQueryClient } from "@tanstack/react-query";

// Server-side, unlike the toggles above it: the DM is sent by a worker, so the preference has to
// be readable when this app is closed.
const SETTING_KEY = "code_comments_slack_dm";

export function SlackCommentNotificationsSettings() {
  const queryClient = useQueryClient();
  const { data: me, isLoading } = useMeQuery();
  const enabled = Boolean(
    (me?.notification_settings as Record<string, unknown> | undefined)?.[
      SETTING_KEY
    ],
  );

  const { mutate, isPending } = useAuthenticatedMutation<void, Error, boolean>(
    async (client, next) =>
      await client.updateNotificationSettings({ [SETTING_KEY]: next }),
    {
      onSuccess: () => {
        void queryClient.invalidateQueries({ queryKey: ["me"] });
      },
    },
  );

  return (
    <>
      <Text className="mt-4 mb-1 block border-gray-6 border-t pt-4 font-medium text-sm">
        Slack
      </Text>
      <Text color="gray" className="mb-1 text-[13px]">
        Comment notifications can also reach you in Slack, so you hear about
        them when PostHog Code isn't open. Link your Slack account under
        Integrations first.
      </Text>

      <SettingRow
        label="Slack DMs for comments"
        description="Get a direct message when someone mentions you, replies to your comment, or comments on something you own"
        noBorder
      >
        <Switch
          checked={enabled}
          onCheckedChange={(next) => mutate(next)}
          disabled={isLoading || isPending}
          size="1"
        />
      </SettingRow>
    </>
  );
}
