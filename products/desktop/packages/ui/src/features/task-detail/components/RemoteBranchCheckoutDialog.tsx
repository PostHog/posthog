import { GitBranch } from "@phosphor-icons/react";
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
import { useRemoteBranchConfirmStore } from "../stores/remoteBranchConfirmStore";

/**
 * Globally-mounted confirmation shown when a user starts a worktree task on a
 * branch that exists only on the remote. Confirming fetches the branch and
 * checks it out locally into the new worktree.
 */
export function RemoteBranchCheckoutDialog() {
  const isOpen = useRemoteBranchConfirmStore((s) => s.isOpen);
  const branch = useRemoteBranchConfirmStore((s) => s.branch);
  const accept = useRemoteBranchConfirmStore((s) => s.accept);
  const cancel = useRemoteBranchConfirmStore((s) => s.cancel);

  return (
    <AlertDialog
      open={isOpen}
      onOpenChange={(open) => {
        if (!open) cancel();
      }}
    >
      <AlertDialogContent className="max-w-[440px]">
        <AlertDialogHeader>
          <AlertDialogTitle>
            <span className="flex items-center gap-2">
              <GitBranch size={18} weight="bold" color="var(--accent-9)" />
              Check out remote branch?
            </span>
          </AlertDialogTitle>
          <AlertDialogDescription>
            {branch ? (
              <code className="font-mono text-foreground">{branch}</code>
            ) : (
              "This branch"
            )}{" "}
            doesn't exist locally but was found on the remote. Check it out into
            a new worktree to continue working on it?
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogClose render={<Button variant="outline" />}>
            Cancel
          </AlertDialogClose>
          <AlertDialogClose
            render={<Button variant="primary" onClick={accept} />}
          >
            Check out branch
          </AlertDialogClose>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
