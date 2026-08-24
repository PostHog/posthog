import { SlackLogoIcon } from "@phosphor-icons/react";
import {
  describeIntegrationDisconnectError,
  isAlreadyDisconnectedError,
} from "@posthog/core/integrations/connectErrors";
import { slackInvalidationKeys } from "@posthog/core/integrations/connectMachine";
import { SLACK_DISCONNECT_DESCRIPTION } from "@posthog/core/integrations/disconnectCopy";
import { Button, Spinner, Text } from "@posthog/quill";
import { formatRelativeTimeLong } from "@posthog/shared";
import { useOptionalAuthenticatedClient } from "@posthog/ui/features/auth/authClient";
import { useAuthStateValue } from "@posthog/ui/features/auth/store";
import { useIsOrgAdmin } from "@posthog/ui/features/auth/useOrgRole";
import { DisconnectIntegrationDialog } from "@posthog/ui/features/integrations/components/DisconnectIntegrationDialog";
import {
  type Integration,
  useIntegrationSelectors,
} from "@posthog/ui/features/integrations/store";
import {
  type SlackConnectResult,
  useSlackConnect,
} from "@posthog/ui/features/integrations/useSlackConnect";
import { toast } from "@posthog/ui/primitives/toast";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

interface SlackWorkspaceConnectionProps {
  /** The page's single connect instance — see `useSlackConnect`. */
  slackConnect: SlackConnectResult;
  isLoading?: boolean;
  /** When false, omit the connect-another button (a parent header renders it). */
  showConnectAnother?: boolean;
}

export function SlackWorkspaceConnection({
  slackConnect,
  isLoading = false,
  showConnectAnother = true,
}: SlackWorkspaceConnectionProps) {
  const { slackIntegrations, hasSlackIntegration } = useIntegrationSelectors();

  if (isLoading) {
    return (
      <div className="flex items-center gap-2 rounded-(--radius-3) border border-(--gray-5) bg-(--color-panel-solid) px-3.5 py-3">
        <Spinner />
        <Text size="xs" variant="muted">
          Loading Slack…
        </Text>
      </div>
    );
  }

  if (hasSlackIntegration) {
    return (
      <div className="flex flex-col gap-2">
        <div className="divide-y divide-(--gray-4) rounded-(--radius-3) border border-(--gray-5) bg-(--color-panel-solid)">
          {slackIntegrations.map((integration) => (
            <SlackWorkspaceRow key={integration.id} integration={integration} />
          ))}
        </div>
        {showConnectAnother ? (
          <div className="flex">
            <Button
              type="button"
              variant="outline"
              size="sm"
              disabled={slackConnect.isConnecting}
              onClick={() => {
                void slackConnect.connect();
              }}
            >
              {slackConnect.isConnecting
                ? "Waiting for Slack…"
                : "Connect another workspace"}
            </Button>
          </div>
        ) : null}
      </div>
    );
  }

  return (
    <div className="flex min-h-11 items-center justify-between gap-6 rounded-(--radius-3) border border-(--gray-5) bg-(--color-panel-solid) px-3.5 py-2">
      <div className="flex min-w-0 flex-col gap-0.5 py-0.5">
        <span className="font-medium text-[13px] text-gray-12 leading-5">
          No Slack workspace connected yet
        </span>
        <span className="text-[12px] text-gray-10 leading-snug">
          Connect a workspace so reports can post to channels and reviewers get
          pinged.
        </span>
      </div>
      <Button
        type="button"
        variant="primary"
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
    </div>
  );
}

function SlackWorkspaceRow({ integration }: { integration: Integration }) {
  const projectId = useAuthStateValue((s) => s.currentProjectId);
  const client = useOptionalAuthenticatedClient();
  const queryClient = useQueryClient();
  const { isAdmin } = useIsOrgAdmin();
  const [confirmOpen, setConfirmOpen] = useState(false);

  const rawDisplayName = integration.display_name;
  const workspaceName =
    (typeof rawDisplayName === "string" && rawDisplayName.trim()) ||
    "Slack workspace";
  const createdAt =
    typeof integration.created_at === "string" ? integration.created_at : null;

  const invalidate = () => {
    for (const queryKey of slackInvalidationKeys()) {
      void queryClient.invalidateQueries({ queryKey: [...queryKey] });
    }
  };

  const disconnect = useMutation({
    mutationFn: async () => {
      if (!client) throw new Error("Not authenticated");
      if (projectId == null) throw new Error("No project selected");
      await client.deleteIntegration(projectId, integration.id);
    },
    onSuccess: () => {
      setConfirmOpen(false);
      toast.success("Slack workspace disconnected.");
      invalidate();
    },
    onError: (error) => {
      if (isAlreadyDisconnectedError(error)) {
        setConfirmOpen(false);
        toast.info("Already disconnected.");
        invalidate();
        return;
      }
      toast.error(
        describeIntegrationDisconnectError(
          error,
          "Failed to disconnect Slack.",
        ),
      );
    },
  });

  return (
    <>
      <div className="flex min-h-11 items-center justify-between gap-6 px-3.5 py-2.5">
        <div className="flex min-w-0 flex-1 items-center gap-3">
          <div className="shrink-0 text-(--gray-11)">
            <SlackLogoIcon size={24} />
          </div>
          <div className="flex min-w-0 flex-col gap-0.5">
            <span className="truncate font-medium text-[13px] text-gray-12 leading-5">
              {workspaceName}
            </span>
            {createdAt ? (
              <span className="truncate text-[12px] text-gray-10 leading-snug">
                Connected {formatRelativeTimeLong(createdAt)}
              </span>
            ) : null}
          </div>
        </div>
        {isAdmin === true ? (
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="shrink-0 text-(--red-11)"
            disabled={disconnect.isPending}
            onClick={() => setConfirmOpen(true)}
          >
            Disconnect
          </Button>
        ) : null}
      </div>
      <DisconnectIntegrationDialog
        open={confirmOpen}
        title={`Disconnect ${workspaceName}?`}
        description={SLACK_DISCONNECT_DESCRIPTION}
        isPending={disconnect.isPending}
        onConfirm={() => disconnect.mutate()}
        onCancel={() => setConfirmOpen(false)}
      />
    </>
  );
}

export function SlackWorkspaceConnectionCallouts({
  slackConnect,
}: {
  slackConnect: SlackConnectResult;
}) {
  if (!slackConnect.hasError && !slackConnect.isTimedOut) {
    return null;
  }

  return (
    <div className="flex flex-col gap-2">
      {slackConnect.hasError && slackConnect.error ? (
        <div className="rounded-(--radius-2) border border-(--red-6) bg-(--red-2) px-3 py-2">
          <Text size="xs" className="text-(--red-11)">
            {slackConnect.error.message}
          </Text>
        </div>
      ) : null}
      {slackConnect.isTimedOut ? (
        <div className="rounded-(--radius-2) border border-(--gray-5) bg-(--gray-2) px-3 py-2">
          <Text size="xs" variant="muted">
            We didn't hear back from PostHog. If you completed the connection in
            your browser it should appear shortly, otherwise try again.
          </Text>
        </div>
      ) : null}
    </div>
  );
}

/**
 * The workspace rows plus their connect callouts, sharing one connect instance. For surfaces
 * that render both together and have no connect action of their own in the header.
 */
export function SlackWorkspaceConnectionBlock({
  isLoading = false,
}: {
  isLoading?: boolean;
}) {
  const slackConnect = useSlackConnect();

  return (
    <>
      <SlackWorkspaceConnection
        slackConnect={slackConnect}
        isLoading={isLoading}
      />
      <SlackWorkspaceConnectionCallouts slackConnect={slackConnect} />
    </>
  );
}
