import { Button, Switch } from "@posthog/quill";
import { useMeQuery } from "@posthog/ui/features/auth/useMeQuery";
import {
  SettingsCard,
  SettingsCardRow,
  SettingsSection,
} from "@posthog/ui/features/settings/components/SettingsCard";
import { useAuthenticatedMutation } from "@posthog/ui/hooks/useAuthenticatedMutation";
import { useAuthenticatedQuery } from "@posthog/ui/hooks/useAuthenticatedQuery";
import { toast } from "@posthog/ui/primitives/toast";
import { openExternalUrl } from "@posthog/ui/shell/openExternal";
import { useQueryClient } from "@tanstack/react-query";

// Server-side, unlike the toggles above it: the DM is sent by a worker, so the preference has to
// be readable when this app is closed.
const SETTING_KEY = "task_comments_slack_dm";

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
      onError: (error) =>
        toast.error("Couldn't update Slack notifications", {
          description: error.message,
        }),
    },
  );

  // Slack's OAuth callback tells us which Slack user authorized, so the link is established
  // without anyone entering an ID.
  const { mutate: connect, isPending: connecting } = useAuthenticatedMutation<
    void,
    Error,
    void
  >(
    async (client) => {
      const { install_url } = await client.startSlackUserIntegrationConnect();
      openExternalUrl(install_url);
    },
    {
      onSuccess: () => {
        void queryClient.invalidateQueries({
          queryKey: ["slack-user-integrations"],
        });
      },
      // The endpoint refuses when the project has no Slack app connected, or when the org is
      // outside the rollout. Without this the button does nothing, which reads as a broken build.
      onError: (error) =>
        toast.error("Couldn't start Slack linking", {
          description: error.message,
        }),
    },
  );

  return (
    <SettingsSection
      label="Comment notifications"
      description="Comment notifications can also reach you in Slack, so you hear about them when PostHog Code isn't open"
    >
      <SettingsCard>
        <SettingsCardRow
          label="Slack account"
          description={
            linked
              ? `Linked to ${links?.[0]?.slack_team_name ?? "Slack"}`
              : "Only needed when your Slack email differs from your PostHog email; otherwise we find you by email"
          }
        >
          {linked ? (
            <span className="text-[12px] text-muted-foreground">Linked</span>
          ) : (
            <Button
              size="sm"
              variant="outline"
              loading={connecting}
              disabled={linksLoading}
              onClick={() => connect()}
            >
              Link Slack account
            </Button>
          )}
        </SettingsCardRow>

        <SettingsCardRow
          label="Slack DMs for comments"
          description="Get a direct message when someone mentions you, replies to your comment, or comments on something you own"
        >
          {/* Deliberately not gated on a link: an unlinked recipient is matched to Slack by
              email, so gating here would hide a path that works. */}
          <Switch
            size="sm"
            checked={enabled}
            onCheckedChange={(next) => mutate(next)}
            disabled={isLoading || isPending}
          />
        </SettingsCardRow>
      </SettingsCard>
    </SettingsSection>
  );
}
