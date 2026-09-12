import { ArtifactShareDialog } from "./ArtifactShareDialog";
import { CanvasShareDialog } from "./CanvasShareDialog";
import type { ShareSurface, ShareTarget } from "./shareTarget";

/**
 * One dialog for everything a person can share out of the app: the link that
 * opens it here, who that link works for, and the public toggle. Mounted only
 * while open, so each opening starts from fresh queries.
 */
export function ShareModal({
  target,
  surface,
  onClose,
}: {
  target: ShareTarget;
  surface: ShareSurface;
  onClose: () => void;
}) {
  if (target.kind === "canvas") {
    return (
      <CanvasShareDialog
        channelId={target.channelId}
        dashboardId={target.dashboardId}
        name={target.name}
        surface={surface}
        onClose={onClose}
      />
    );
  }
  return (
    <ArtifactShareDialog
      taskId={target.taskId}
      artifactId={target.artifactId}
      name={target.name}
      onClose={onClose}
    />
  );
}
