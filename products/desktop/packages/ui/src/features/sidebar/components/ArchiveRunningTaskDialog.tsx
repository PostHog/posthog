import { Warning } from "@phosphor-icons/react";
import {
  AlertDialog,
  AlertDialogClose,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  Button,
} from "@posthog/quill";
import { useState } from "react";

interface ArchiveRunningTaskDialogProps {
  open: boolean;
  taskTitle: string;
  stopsCloudSandbox: boolean;
  onConfirm: () => Promise<void>;
  onCancel: () => void;
}

export function ArchiveRunningTaskDialog({
  open,
  taskTitle,
  stopsCloudSandbox,
  onConfirm,
  onCancel,
}: ArchiveRunningTaskDialogProps) {
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleConfirm = async (event: React.MouseEvent) => {
    event.preventDefault();
    if (isSubmitting) return;
    setIsSubmitting(true);
    setError(null);
    try {
      await onConfirm();
    } catch (caughtError) {
      setError(
        caughtError instanceof Error
          ? caughtError.message
          : "Couldn't archive the task. Try again in a moment.",
      );
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <AlertDialog
      open={open}
      onOpenChange={(isOpen) => {
        if (!isOpen && !isSubmitting) {
          setError(null);
          onCancel();
        }
      }}
    >
      <AlertDialogContent className="max-w-[420px]">
        <AlertDialogHeader>
          <AlertDialogTitle>
            <span className="flex items-center gap-2">
              <Warning size={18} weight="fill" color="var(--orange-9)" />
              Archive running task?
            </span>
          </AlertDialogTitle>
          <AlertDialogDescription>
            {taskTitle ? `"${taskTitle}"` : "This task"} is still running.
            {stopsCloudSandbox
              ? " Archiving it will stop its cloud run and shut down the sandbox."
              : " Archiving it now will stop the agent."}{" "}
            You can unarchive it later.
          </AlertDialogDescription>
          {error ? <p className="text-destructive text-sm">{error}</p> : null}
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogClose
            render={
              <Button variant="outline" size="sm" disabled={isSubmitting} />
            }
          >
            Cancel
          </AlertDialogClose>
          <Button
            variant="destructive-outline"
            size="sm"
            disabled={isSubmitting}
            loading={isSubmitting}
            onClick={handleConfirm}
          >
            Archive
          </Button>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
