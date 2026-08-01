import { SlackLogoIcon } from "@phosphor-icons/react";
import { Button } from "@posthog/quill";
import { formatRelativeTimeLong } from "@posthog/shared";
import {
  type Integration,
  useIntegrationSelectors,
} from "@posthog/ui/features/integrations/store";
import { useSlackConnect } from "@posthog/ui/features/integrations/useSlackConnect";
import { Box, Callout, Flex, Spinner, Text } from "@radix-ui/themes";

interface SlackWorkspaceConnectionProps {
  isLoading?: boolean;
}

export function SlackWorkspaceConnection({
  isLoading = false,
}: SlackWorkspaceConnectionProps) {
  const { slackIntegrations, hasSlackIntegration } = useIntegrationSelectors();
  const slackConnect = useSlackConnect();

  if (isLoading) {
    return (
      <Flex align="center" gap="2" py="1">
        <Spinner size="1" />
        <Text className="text-(--gray-11) text-[13px]">Loading Slack…</Text>
      </Flex>
    );
  }

  if (hasSlackIntegration) {
    return (
      <Flex direction="column" gap="2">
        {slackIntegrations.map((integration) => (
          <SlackWorkspaceRow key={integration.id} integration={integration} />
        ))}
      </Flex>
    );
  }

  return (
    <Flex
      align="center"
      justify="between"
      gap="4"
      className="rounded-(--radius-2) border border-border bg-(--color-panel-solid) px-4 py-3.5"
    >
      <Flex align="center" gap="3" className="min-w-0">
        <Box className="shrink-0 text-(--gray-11)">
          <SlackLogoIcon size={20} />
        </Box>
        <Flex direction="column" gap="1" className="min-w-0">
          <Text className="font-medium text-(--gray-12) text-sm">
            Slack workspace
          </Text>
          <Text className="text-(--gray-11) text-[13px] leading-snug">
            Connect a workspace so reports can post to channels and reviewers
            get pinged.
          </Text>
        </Flex>
      </Flex>
      <Button
        type="button"
        variant="outline"
        size="sm"
        className="shrink-0"
        disabled={slackConnect.isConnecting}
        onClick={() => {
          void slackConnect.connect();
        }}
      >
        {slackConnect.isConnecting
          ? "Waiting for Slack…"
          : "Connect Slack workspace"}
      </Button>
    </Flex>
  );
}

function SlackWorkspaceRow({ integration }: { integration: Integration }) {
  const rawDisplayName = integration.display_name;
  const workspaceName =
    (typeof rawDisplayName === "string" && rawDisplayName.trim()) ||
    "Slack workspace";
  const createdAt =
    typeof integration.created_at === "string" ? integration.created_at : null;

  return (
    <Flex
      align="center"
      gap="3"
      className="rounded-(--radius-2) border border-border bg-(--color-panel-solid) px-4 py-3.5"
    >
      <Box className="shrink-0 text-(--gray-11)">
        <SlackLogoIcon size={24} />
      </Box>
      <Flex direction="column" gap="0.5" className="min-w-0">
        <Text className="text-(--gray-12) text-sm">
          <Text className="font-medium">Connected</Text> to{" "}
          <Text className="font-medium">{workspaceName}</Text>
        </Text>
        {createdAt ? (
          <Text className="text-(--gray-11) text-[13px]">
            Connected {formatRelativeTimeLong(createdAt)}
          </Text>
        ) : null}
      </Flex>
    </Flex>
  );
}

export function SlackWorkspaceConnectionCallouts() {
  const slackConnect = useSlackConnect();

  if (!slackConnect.hasError && !slackConnect.isTimedOut) {
    return null;
  }

  return (
    <Flex direction="column" gap="2">
      {slackConnect.hasError && slackConnect.error ? (
        <Callout.Root size="1" color="red" variant="soft">
          <Callout.Text>{slackConnect.error.message}</Callout.Text>
        </Callout.Root>
      ) : null}
      {slackConnect.isTimedOut ? (
        <Callout.Root size="1" color="gray" variant="soft">
          <Callout.Text>
            We didn't hear back from PostHog. If you completed the connection in
            your browser it should appear shortly, otherwise try again.
          </Callout.Text>
        </Callout.Root>
      ) : null}
    </Flex>
  );
}
