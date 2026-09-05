import { ArrowSquareOutIcon, InfoIcon } from "@phosphor-icons/react";
import {
  describeGithubConnectError,
  GITHUB_CODE_CONTEXT_MESSAGE,
  GITHUB_CONNECT_TIMEOUT_MESSAGE,
} from "@posthog/core/integrations/connectErrors";
import { Button, Spinner } from "@posthog/quill";
import { useAuthStateValue } from "@posthog/ui/features/auth/store";
import { useGithubConnect } from "@posthog/ui/features/integrations/useGithubUserConnect";
import { useRepositoryIntegration } from "@posthog/ui/features/integrations/useIntegrations";

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
    <div className="flex flex-wrap items-center justify-between gap-2 rounded-(--radius-2) border border-(--yellow-6) bg-(--yellow-2) px-3 py-2 text-(--yellow-12)">
      <div className="flex min-w-0 flex-1 items-start gap-2">
        <InfoIcon className="mt-0.5 shrink-0" size={14} />
        <p className="m-0 text-xs">
          {hasError
            ? describeGithubConnectError(error)
            : isTimedOut
              ? GITHUB_CONNECT_TIMEOUT_MESSAGE
              : GITHUB_CODE_CONTEXT_MESSAGE}
        </p>
      </div>
      <Button
        type="button"
        size="sm"
        variant="outline"
        disabled={!canConnect || isConnecting}
        data-attr="connect-github-for-cloud-tasks"
        onClick={() => {
          if (!canConnect) return;
          if (hasError) reset();
          void connect();
        }}
      >
        {isConnecting ? <Spinner /> : <ArrowSquareOutIcon size={12} />}
        {isConnecting
          ? "Waiting for GitHub…"
          : hasError || isTimedOut
            ? "Try again"
            : "Connect GitHub"}
      </Button>
    </div>
  );
}
