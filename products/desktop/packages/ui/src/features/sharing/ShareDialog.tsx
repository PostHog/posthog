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

/** The frame every share body sits in: a title, the thing's name, the body, and a Done button. */
export function ShareDialog({
  title,
  description,
  onClose,
  action,
  children,
}: {
  title: string;
  description: string;
  onClose: () => void;
  /** A primary action shown next to Done, such as publishing changes to the public link. */
  action?: ReactNode;
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
          {action}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
