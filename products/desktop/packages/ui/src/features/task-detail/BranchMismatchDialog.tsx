import { GitBranch, Warning } from "@phosphor-icons/react";
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

interface BranchMismatchDialogProps {
  open: boolean;
  linkedBranch: string;
  currentBranch: string;
  hasUncommittedChanges: boolean;
  switchError: string | null;
  onSwitch: () => void;
  onContinue: () => void;
  onCancel: () => void;
  isSwitching?: boolean;
}

function BranchLabel({ name }: { name: string }) {
  return (
    <code className="inline-flex max-w-full items-center gap-1 text-sm">
      <GitBranch size={12} className="shrink-0" />
      <span className="truncate">{name}</span>
    </code>
  );
}

export function BranchMismatchDialog({
  open,
  linkedBranch,
  currentBranch,
  hasUncommittedChanges,
  switchError,
  onSwitch,
  onContinue,
  onCancel,
  isSwitching,
}: BranchMismatchDialogProps) {
  return (
    <AlertDialog
      open={open}
      onOpenChange={(isOpen) => {
        if (!isOpen) onCancel();
      }}
    >
      <AlertDialogContent className="max-w-[420px]">
        <AlertDialogHeader>
          <AlertDialogTitle>
            <span className="flex items-center gap-2">
              <Warning size={18} weight="fill" color="var(--orange-9)" />
              Wrong branch
            </span>
          </AlertDialogTitle>
          <AlertDialogDescription>
            This task is linked to a different branch than the one you're
            currently on. The agent will make changes on the current branch.
          </AlertDialogDescription>
        </AlertDialogHeader>
        <div className="flex min-w-0 flex-col gap-3 px-4 py-3">
          <div className="flex min-w-0 flex-col gap-1">
            <div className="flex min-w-0 items-center gap-2">
              <span className="w-16 shrink-0 text-[13px] text-muted-foreground">
                Linked
              </span>
              <BranchLabel name={linkedBranch} />
            </div>
            <div className="flex min-w-0 items-center gap-2">
              <span className="w-16 shrink-0 text-[13px] text-muted-foreground">
                Current
              </span>
              <BranchLabel name={currentBranch} />
            </div>
          </div>

          {hasUncommittedChanges && !switchError && (
            <div className="rounded-md bg-muted p-2 text-muted-foreground text-xs">
              You have uncommitted changes on your current branch. If needed,
              commit or stash them first.
            </div>
          )}

          {switchError && (
            <div className="rounded-md bg-destructive/10 p-2 text-destructive text-xs">
              {switchError}
            </div>
          )}
        </div>
        <AlertDialogFooter>
          <AlertDialogClose
            render={
              <Button variant="outline" size="sm" disabled={isSwitching} />
            }
          >
            Cancel
          </AlertDialogClose>
          <AlertDialogClose
            render={
              <Button
                variant="secondary"
                size="sm"
                onClick={onContinue}
                disabled={isSwitching}
              />
            }
          >
            Continue anyway
          </AlertDialogClose>
          <Button
            variant="primary"
            size="sm"
            onClick={onSwitch}
            disabled={isSwitching}
            loading={isSwitching}
          >
            Switch branch
          </Button>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
