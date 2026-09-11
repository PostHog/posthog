import { FolderOpen, Warning } from "@phosphor-icons/react";
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
import { useExistingWorktreeConfirmStore } from "../stores/existingWorktreeConfirmStore";

/**
 * Globally-mounted confirmation shown when a user starts a worktree task on a
 * branch that already has a worktree checked out. Confirming reuses that
 * worktree for the task instead of creating a new one.
 */
export function ExistingWorktreeDialog() {
  const isOpen = useExistingWorktreeConfirmStore((s) => s.isOpen);
  const branch = useExistingWorktreeConfirmStore((s) => s.branch);
  const worktreePath = useExistingWorktreeConfirmStore((s) => s.worktreePath);
  const accept = useExistingWorktreeConfirmStore((s) => s.accept);
  const cancel = useExistingWorktreeConfirmStore((s) => s.cancel);

  return (
    <AlertDialog
      open={isOpen}
      onOpenChange={(open) => {
        if (!open) cancel();
      }}
    >
      <AlertDialogContent className="max-w-[460px]">
        <AlertDialogHeader>
          <AlertDialogTitle>
            <span className="flex items-center gap-2">
              <FolderOpen size={18} weight="bold" color="var(--accent-9)" />
              Worktree already exists
            </span>
          </AlertDialogTitle>
          <AlertDialogDescription>
            A worktree is already checked out on{" "}
            {branch ? (
              <code className="font-mono text-foreground">{branch}</code>
            ) : (
              "this branch"
            )}
            {worktreePath ? (
              <>
                {" "}
                at{" "}
                <code className="font-mono text-foreground">
                  {worktreePath}
                </code>
              </>
            ) : null}
            . Continue and use that worktree for this task?
          </AlertDialogDescription>
        </AlertDialogHeader>
        <div className="px-4 py-3">
          <div className="flex items-start gap-2 text-muted-foreground text-xs">
            <Warning
              size={16}
              weight="bold"
              color="var(--amber-9)"
              className="mt-px shrink-0"
            />
            <p>
              Deleting this task later removes the worktree and any uncommitted
              work in it, even though it existed beforehand.
            </p>
          </div>
        </div>
        <AlertDialogFooter>
          <AlertDialogClose render={<Button variant="outline" />}>
            Cancel
          </AlertDialogClose>
          <AlertDialogClose
            render={<Button variant="primary" onClick={accept} />}
          >
            Use existing worktree
          </AlertDialogClose>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
