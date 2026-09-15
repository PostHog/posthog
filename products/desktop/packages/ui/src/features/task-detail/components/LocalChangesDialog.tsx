import {
  AlertDialog,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  Button,
  DialogBody,
} from "@posthog/quill";

export interface LocalChangesDialogProps {
  open: boolean;
  stagedFiles: string[];
  unstagedFiles: string[];
  untrackedFiles: string[];
  isStashing: boolean;
  stashError: string | null;
  onOpenChange: (open: boolean) => void;
  onCancel: () => void;
  onContinue: () => void;
  onStashAndContinue: () => void;
}

function renderFileGroup(
  title: string,
  files: string[],
): React.JSX.Element | null {
  if (files.length === 0) return null;

  return (
    <section className="flex flex-col gap-1.5">
      <h3 className="font-medium text-sm">
        {title} ({files.length})
      </h3>
      <ul className="max-h-28 overflow-y-auto rounded-md border border-border bg-muted/30 px-3 py-2 font-mono text-muted-foreground text-xs">
        {files.map((file) => (
          <li key={file} className="truncate">
            {file}
          </li>
        ))}
      </ul>
    </section>
  );
}

export function LocalChangesDialog({
  open,
  stagedFiles,
  unstagedFiles,
  untrackedFiles,
  isStashing,
  stashError,
  onOpenChange,
  onCancel,
  onContinue,
  onStashAndContinue,
}: LocalChangesDialogProps): React.JSX.Element {
  return (
    <AlertDialog
      open={open}
      onOpenChange={(next) => {
        if (!next && !isStashing) onOpenChange(next);
      }}
    >
      <AlertDialogContent className="max-w-md">
        <AlertDialogHeader>
          <AlertDialogTitle>Local changes found</AlertDialogTitle>
          <AlertDialogDescription>
            This folder has local changes. A local task can mix its work with
            these changes. Stashed changes stay in Git until you restore them.
          </AlertDialogDescription>
        </AlertDialogHeader>
        <DialogBody>
          <div className="flex flex-col gap-3">
            {renderFileGroup("Staged", stagedFiles)}
            {renderFileGroup("Unstaged", unstagedFiles)}
            {renderFileGroup("Untracked", untrackedFiles)}
            {stashError ? (
              <p className="text-destructive text-sm" role="alert">
                {stashError}
              </p>
            ) : null}
          </div>
        </DialogBody>
        <AlertDialogFooter>
          <Button
            variant="outline"
            size="sm"
            data-attr="task-local-changes-cancel"
            disabled={isStashing}
            onClick={onCancel}
          >
            Cancel
          </Button>
          <Button
            variant="outline"
            size="sm"
            data-attr="task-local-changes-continue"
            disabled={isStashing}
            onClick={onContinue}
          >
            Continue
          </Button>
          <Button
            variant="primary"
            size="sm"
            data-attr="task-local-changes-stash-and-continue"
            disabled={isStashing}
            loading={isStashing}
            onClick={onStashAndContinue}
          >
            Stash and continue
          </Button>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
