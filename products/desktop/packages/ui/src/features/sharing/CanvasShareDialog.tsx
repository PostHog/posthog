import type { CanvasSharing } from "@posthog/core/canvas/dashboardSchemas";
import { Button, Label, Separator, Switch, Text } from "@posthog/quill";
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
import { AccessSection } from "./AccessSection";
import { LinkCopyRow } from "./LinkCopyRow";
import { PublicShareSection } from "./PublicShareSection";
import { publicLinkHasUnpublishedChanges } from "./publicLink";
import { ShareDialog } from "./ShareDialog";
import type { ShareSurface, ShareVisibility } from "./shareTarget";
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

  return (
    <div className="flex flex-col gap-5">
      <LinkCopyRow
        label="Team link"
        description="For people on your team. Opens the canvas straight in PostHog Desktop."
        url={appUrl}
        copiedDescription="Anyone on your team with access can open the canvas."
        dataAttr="share-canvas-copy-link"
        onCopied={onLinkCopied}
      />
      <LinkCopyRow
        label="Link to a copy"
        description="Whoever opens it gets their own editable copy in their personal space. This canvas stays as it is."
        url={forkUrl}
        copiedDescription="Opening it creates a copy of the canvas."
        dataAttr="share-canvas-copy-fork-link"
        onCopied={onForkLinkCopied}
      />
      <AccessSection visibility={visibility} noun="canvas" />
      {isPubliclyShareable ? (
        <>
          <Separator />
          <PublicShareSection
            sharing={sharing}
            isLoading={isLoading}
            isError={isError}
            isPending={isPending}
            publicUrl={publicUrl}
            description="Anyone with the link can view the canvas as it was when you shared it. Changes made after that stay private until you publish them. Live data isn't shown."
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
                The canvas changed after you shared it. Publish the changes to
                update the public link.
              </Text>
            )}
            <div className="flex items-start gap-3">
              <Switch
                id={allowForkingId}
                checked={sharing?.allowForking ?? false}
                disabled={isPending}
                onCheckedChange={(checked) => onAllowForkingChange(checked)}
                data-attr="share-canvas-allow-forking-toggle"
              />
              <div className="flex min-w-0 flex-col gap-0.5">
                <Label htmlFor={allowForkingId}>Let viewers make a copy</Label>
                <Text size="xs" variant="muted">
                  Anyone with the link can copy the canvas into their own
                  PostHog project.
                </Text>
              </div>
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
