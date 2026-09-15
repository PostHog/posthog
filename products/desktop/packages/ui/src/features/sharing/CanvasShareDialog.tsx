import type { CanvasSharing } from "@posthog/core/canvas/dashboardSchemas";
import {
  Button,
  Label,
  Separator,
  Switch,
  Text,
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@posthog/quill";
import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import { useChannels } from "@posthog/ui/features/canvas/hooks/useChannels";
import { useDashboard } from "@posthog/ui/features/canvas/hooks/useDashboards";
import { track } from "@posthog/ui/shell/analytics";
import {
  canvasForkUrl,
  canvasShareUrl,
  sharedResourceUrl,
} from "@posthog/ui/utils/posthogLinks";
import { useId } from "react";
import { copyLinkToClipboard } from "./copyLink";
import { LinkCopyRow } from "./LinkCopyRow";
import { PublicShareSection } from "./PublicShareSection";
import { publicLinkHasUnpublishedChanges } from "./publicLink";
import { ShareDialog } from "./ShareDialog";
import { ShareSection } from "./ShareSection";
import type { ShareSurface, ShareVisibility } from "./shareTarget";
import { teamLinkDescription } from "./teamLinkCopy";
import { useCanvasSharingQuery, useSetCanvasSharing } from "./useCanvasSharing";

export interface CanvasShareBodyViewProps {
  appUrl: string | null;
  forkUrl: string | null;
  publicUrl: string | null;
  visibility: ShareVisibility;
  isPubliclyShareable: boolean;
  sharing: CanvasSharing | null | undefined;
  isLoading: boolean;
  isError: boolean;
  isPending: boolean;
  disabledReason?: string;
  /** A build newer than the one the public link is pinned to is published. */
  newerVersionPublished: boolean;
  onToggle: (enabled: boolean) => void;
  onAllowForkingChange: (allow: boolean) => void;
  onLinkCopied?: (success: boolean) => void;
  onForkLinkCopied?: (success: boolean) => void;
}

/** The share dialog's canvas body, given everything it shows. */
export function CanvasShareBodyView({
  appUrl,
  forkUrl,
  publicUrl,
  visibility,
  isPubliclyShareable,
  sharing,
  isLoading,
  isError,
  isPending,
  disabledReason,
  newerVersionPublished,
  onToggle,
  onAllowForkingChange,
  onLinkCopied,
  onForkLinkCopied,
}: CanvasShareBodyViewProps) {
  const allowForkingId = useId();
  const publicDescription = sharing?.enabled
    ? "Anyone with the link sees the canvas as it was when you shared it. Live data isn't shown."
    : "Anyone with the link can view a snapshot of the canvas. Live data isn't shown.";

  return (
    <div className="flex flex-col gap-5">
      <ShareSection
        title="Team link"
        description={teamLinkDescription(visibility, "canvas")}
      >
        <LinkCopyRow
          label="Team link"
          hideLabel
          url={appUrl}
          copiedDescription="Anyone on your team with access can open the canvas."
          dataAttr="share-canvas-copy-link"
          onCopied={onLinkCopied}
        />
        {forkUrl ? (
          <Tooltip>
            <TooltipTrigger
              render={
                <Button
                  variant="link-muted"
                  size="xs"
                  className="self-start"
                  onClick={() =>
                    void copyLinkToClipboard(
                      forkUrl,
                      "Opening it creates a copy of the canvas.",
                      onForkLinkCopied,
                    )
                  }
                  data-attr="share-canvas-copy-fork-link"
                >
                  Copy template link
                </Button>
              }
            />
            <TooltipContent>
              Whoever opens it gets their own editable copy in their personal
              space. This canvas stays as it is.
            </TooltipContent>
          </Tooltip>
        ) : null}
      </ShareSection>
      {isPubliclyShareable ? (
        <>
          <Separator />
          <PublicShareSection
            sharing={sharing}
            isLoading={isLoading}
            isError={isError}
            isPending={isPending}
            publicUrl={publicUrl}
            description={publicDescription}
            disabledReason={disabledReason}
            dataAttrPrefix="share-canvas"
            onToggle={onToggle}
          >
            {newerVersionPublished && (
              <Text
                size="xs"
                variant="muted"
                data-attr="share-canvas-newer-version"
              >
                Changes since you shared aren't public yet.
              </Text>
            )}
            <div className="flex items-center gap-3">
              <Switch
                id={allowForkingId}
                checked={sharing?.allowForking ?? false}
                disabled={isPending}
                onCheckedChange={(checked) => onAllowForkingChange(checked)}
                data-attr="share-canvas-allow-forking-toggle"
              />
              <Label htmlFor={allowForkingId}>
                Let viewers copy this canvas
              </Label>
            </div>
          </PublicShareSection>
        </>
      ) : null}
    </div>
  );
}

export function CanvasShareDialog({
  channelId,
  dashboardId,
  name,
  surface,
  onClose,
}: {
  channelId: string;
  dashboardId: string;
  name: string;
  surface: ShareSurface;
  onClose: () => void;
}) {
  const { channels, isLoading: channelsLoading } = useChannels();
  const channel = channels.find((candidate) => candidate.id === channelId);
  const visibility: ShareVisibility = channel
    ? channel.channelType === "personal"
      ? "personal"
      : "project"
    : channelsLoading
      ? "unknown"
      : "project";
  // A grid loads its components live through the host, which a public page cannot do, so the
  // server refuses to publish one. Home is a grid, so this is every user's canvas list.
  const { dashboard } = useDashboard(dashboardId);
  const isPubliclyShareable = dashboard ? dashboard.kind !== "grid" : true;
  const sharing = useCanvasSharingQuery(dashboardId);
  // Turning sharing on captures the published build, so there has to be one. An already-shared
  // canvas keeps its toggle so the link can still be turned off.
  const disabledReason =
    dashboard && !dashboard.publishedBuildId && !sharing.data?.enabled
      ? "Publish the canvas before sharing it publicly."
      : undefined;
  const { setEnabled, updateLink, setAllowForking, isPending } =
    useSetCanvasSharing(dashboardId);
  const newerVersionPublished =
    !!sharing.data?.enabled && publicLinkHasUnpublishedChanges(dashboard);
  const analytics = {
    surface,
    channel_id: channelId,
    dashboard_id: dashboardId,
  };
  const publishChanges = () =>
    void updateLink().then((result) =>
      track(ANALYTICS_EVENTS.DASHBOARD_ACTION, {
        action_type: "public_link_updated",
        ...analytics,
        success: result !== null,
      }),
    );

  return (
    <ShareDialog
      title="Share canvas"
      description={name}
      onClose={onClose}
      action={
        newerVersionPublished ? (
          <Button
            variant="primary"
            size="sm"
            loading={isPending}
            onClick={publishChanges}
            data-attr="share-canvas-publish-changes"
          >
            Publish changes
          </Button>
        ) : null
      }
    >
      <CanvasShareBodyView
        appUrl={canvasShareUrl(channelId, dashboardId)}
        forkUrl={canvasForkUrl(channelId, dashboardId)}
        publicUrl={
          sharing.data?.accessToken
            ? sharedResourceUrl(sharing.data.accessToken)
            : null
        }
        visibility={visibility}
        isPubliclyShareable={isPubliclyShareable}
        sharing={sharing.data}
        isLoading={sharing.isLoading}
        isError={sharing.isError}
        isPending={isPending}
        disabledReason={disabledReason}
        newerVersionPublished={newerVersionPublished}
        onToggle={(enabled) =>
          void setEnabled(enabled).then((result) =>
            track(ANALYTICS_EVENTS.DASHBOARD_ACTION, {
              action_type: "public_share_toggled",
              ...analytics,
              public: enabled,
              success: result !== null,
            }),
          )
        }
        onAllowForkingChange={(checked) => void setAllowForking(checked)}
        onLinkCopied={(success) =>
          track(ANALYTICS_EVENTS.DASHBOARD_ACTION, {
            action_type: "link_copied",
            ...analytics,
            success,
          })
        }
        onForkLinkCopied={(success) =>
          track(ANALYTICS_EVENTS.DASHBOARD_ACTION, {
            action_type: "fork_link_copied",
            ...analytics,
            success,
          })
        }
      />
    </ShareDialog>
  );
}
