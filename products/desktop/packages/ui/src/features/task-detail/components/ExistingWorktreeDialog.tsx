import { FolderOpen, Warning } from "@phosphor-icons/react";
import {
  AlertDialog,
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
    <AlertDialog open={isOpen} onOpenChange={() => undefined}>
      <AlertDialogContent className="max-w-[460px]">
        <AlertDialogHeader>
          <AlertDialogTitle>
            <span className="flex items-center gap-2">
              <FolderOpen size={18} weight="bold" color="var(--accent-9)" />
              Worktree already exists
            </span>
          </AlertDialogTitle>
          <AlertDialogDescription render={<div />}>
            <p>
              A worktree is already checked out on{" "}
              {branch ? <code>{branch}</code> : "this branch"}
              {worktreePath ? (
                <>
                  {" "}
                  at <code>{worktreePath}</code>
                </>
              ) : null}
              . Continue and use that worktree for this task?
            </p>
          </AlertDialogDescription>
        </AlertDialogHeader>

        <div className="flex items-start gap-2">
          <Warning
            size={16}
            weight="bold"
            color="var(--amber-9)"
            className="mt-px shrink-0"
          />
          <p className="text-muted-foreground text-sm">
            Deleting this task later removes the worktree and any uncommitted
            work in it, even though it existed beforehand.
          </p>
        </div>

        <AlertDialogFooter>
          <Button variant="outline" onClick={cancel}>
            Cancel
          </Button>
          <Button variant="primary" onClick={accept}>
            Use existing worktree
          </Button>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
