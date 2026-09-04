import { Label, Separator, Switch, Text } from "@posthog/quill";
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
import type { ShareSurface, ShareVisibility } from "./shareTarget";
import { useCanvasSharingQuery, useSetCanvasSharing } from "./useCanvasSharing";

export function CanvasShareBody({
  channelId,
  dashboardId,
  surface,
}: {
  channelId: string;
  dashboardId: string;
  surface: ShareSurface;
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
  const { setEnabled, setAllowForking, isPending } =
    useSetCanvasSharing(dashboardId);
  const publicUrl = sharing.data?.accessToken
    ? sharedResourceUrl(sharing.data.accessToken)
    : null;
  const allowForkingId = useId();
  const analytics = {
    surface,
    channel_id: channelId,
    dashboard_id: dashboardId,
  };

  return (
    <div className="flex flex-col gap-5">
      <LinkCopyRow
        label="Link"
        description="Opens the canvas in PostHog Desktop."
        url={canvasShareUrl(channelId, dashboardId)}
        copiedDescription="Anyone in this project with access can open the canvas."
        dataAttr="share-canvas-copy-link"
        onCopied={(success) =>
          track(ANALYTICS_EVENTS.DASHBOARD_ACTION, {
            action_type: "link_copied",
            ...analytics,
            success,
          })
        }
      />
      <LinkCopyRow
        label="Link to a copy"
        description="Whoever opens it gets their own editable copy in their personal space. This canvas stays as it is."
        url={canvasForkUrl(channelId, dashboardId)}
        copiedDescription="Opening it creates a copy of the canvas."
        dataAttr="share-canvas-copy-fork-link"
        onCopied={(success) =>
          track(ANALYTICS_EVENTS.DASHBOARD_ACTION, {
            action_type: "fork_link_copied",
            ...analytics,
            success,
          })
        }
      />
      <AccessSection visibility={visibility} noun="canvas" />
      {isPubliclyShareable ? (
        <>
          <Separator />
          <PublicShareSection
            sharing={sharing.data}
            isLoading={sharing.isLoading}
            isError={sharing.isError}
            isPending={isPending}
            publicUrl={publicUrl}
            description="Anyone with the link can view a snapshot of the published canvas. Live data isn't shown in the public view."
            dataAttrPrefix="share-canvas"
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
          >
            <div className="flex items-start gap-3">
              <Switch
                id={allowForkingId}
                checked={sharing.data?.allowForking ?? false}
                disabled={isPending}
                onCheckedChange={(checked) => void setAllowForking(checked)}
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
