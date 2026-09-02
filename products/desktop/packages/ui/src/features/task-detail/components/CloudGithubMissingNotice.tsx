import { ArrowSquareOutIcon, InfoIcon } from "@phosphor-icons/react";
import {
  describeGithubConnectError,
  GITHUB_CONNECT_TIMEOUT_MESSAGE,
} from "@posthog/core/integrations/connectErrors";
import { useAuthStateValue } from "@posthog/ui/features/auth/store";
import { useGithubConnect } from "@posthog/ui/features/integrations/useGithubUserConnect";
import { useRepositoryIntegration } from "@posthog/ui/features/integrations/useIntegrations";
import { Button, Callout, Flex, Spinner, Text } from "@radix-ui/themes";

export function CloudGithubMissingNotice() {
  const projectId = useAuthStateValue((s) => s.currentProjectId);
  const cloudRegion = useAuthStateValue((s) => s.cloudRegion);
  const { hasGithubIntegration: hasTeamGithubIntegration } =
    useRepositoryIntegration();
  const { error, isConnecting, isTimedOut, hasError, connect, reset } =
    useGithubConnect({
      projectId,
      projectHasTeamIntegration: hasTeamGithubIntegration,
    });
  const canConnect = projectId != null && cloudRegion != null;

  return (
    <Callout.Root color="amber" variant="soft" size="1">
      <Flex align="center" gap="2" justify="between" wrap="wrap">
        <Flex align="start" gap="2" className="min-w-0 flex-1">
          <Callout.Icon>
            <InfoIcon size={14} />
          </Callout.Icon>
          <Callout.Text>
            <Text size="1">
              {hasError
                ? describeGithubConnectError(error)
                : isTimedOut
                  ? GITHUB_CONNECT_TIMEOUT_MESSAGE
                  : "Connect GitHub to your PostHog account for cloud tasks."}
            </Text>
          </Callout.Text>
        </Flex>
        <Button
          size="1"
          variant="soft"
          color="amber"
          disabled={!canConnect || isConnecting}
          onClick={() => {
            if (!canConnect) return;
            if (hasError) reset();
            void connect();
          }}
        >
          {isConnecting ? (
            <Spinner size="1" />
          ) : (
            <ArrowSquareOutIcon size={12} />
          )}
          {isConnecting
            ? "Waiting…"
            : hasError || isTimedOut
              ? "Try again"
              : "Connect GitHub"}
        </Button>
      </Flex>
    </Callout.Root>
  );
}
