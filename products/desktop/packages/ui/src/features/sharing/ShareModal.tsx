import {
  Button,
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@posthog/quill";
import { ArtifactShareBody } from "./ArtifactShareBody";
import { CanvasShareBody } from "./CanvasShareBody";
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
  return (
    <Dialog
      open
      onOpenChange={(next) => {
        if (!next) onClose();
      }}
    >
      <DialogContent className="max-w-[520px]">
        <DialogHeader>
          <DialogTitle>
            {target.kind === "canvas" ? "Share canvas" : "Share file"}
          </DialogTitle>
          <DialogDescription>{target.name}</DialogDescription>
        </DialogHeader>
        <DialogBody>
          {target.kind === "canvas" ? (
            <CanvasShareBody
              channelId={target.channelId}
              dashboardId={target.dashboardId}
              surface={surface}
            />
          ) : (
            <ArtifactShareBody
              taskId={target.taskId}
              artifactId={target.artifactId}
              name={target.name}
            />
          )}
        </DialogBody>
        <DialogFooter>
          <Button
            variant="outline"
            size="sm"
            onClick={onClose}
            data-attr="share-modal-done"
          >
            Done
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
