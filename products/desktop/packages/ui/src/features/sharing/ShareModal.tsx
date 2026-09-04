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
import type { ReactNode } from "react";
import { ArtifactShareBody } from "./ArtifactShareBody";
import { CanvasShareBody } from "./CanvasShareBody";
import type { ShareSurface, ShareTarget } from "./shareTarget";

/** The frame every share body sits in: a title, the thing's name, the body, a Done button. */
export function ShareDialog({
  title,
  description,
  onClose,
  children,
}: {
  title: string;
  description: string;
  onClose: () => void;
  children: ReactNode;
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
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription>{description}</DialogDescription>
        </DialogHeader>
        <DialogBody>{children}</DialogBody>
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
    <ShareDialog
      title={target.kind === "canvas" ? "Share canvas" : "Share file"}
      description={target.name}
      onClose={onClose}
    >
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
        />
      )}
    </ShareDialog>
  );
}
